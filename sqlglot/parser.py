import re
from . import expressions as exp


class SimpleTree:
    def __init__(self, sql: str):
        self.sql = sql

    def find_all(self, cls):
        results = []
        s = self.sql
        if cls is exp.Table:
            # find FROM and JOIN table refs
            for m in re.finditer(
                r"(?:FROM|JOIN)\s+([A-Za-z0-9_\.]+)(?:\s+AS\s+([A-Za-z0-9_]+))?",
                s,
                re.IGNORECASE,
            ):
                full = m.group(1)
                alias = m.group(2)
                # split schema.table if present
                if "." in full:
                    schema, name = full.split(".", 1)
                    results.append(exp.Table(name, alias=alias, db=schema))
                else:
                    results.append(exp.Table(full, alias=alias))
        elif cls is exp.Column:
            # crude: capture portion between SELECT and FROM
            sel = re.search(r"SELECT\s+(.*?)\s+FROM", s, re.IGNORECASE | re.DOTALL)
            if sel:
                cols = sel.group(1)
                parts = [c.strip() for c in cols.split(",")]
                for p in parts:
                    # handle alias AS
                    p = re.sub(r"\s+AS\s+.*$", "", p, flags=re.IGNORECASE)
                    if "." in p:
                        left, right = p.rsplit(".", 1)
                        # strip schema if three-part name
                        if "." in left:
                            left = left.split(".")[-1]
                        results.append(exp.Column(right.strip(), table=left.strip()))
                    else:
                        # single token col
                        # remove functions and parens simplistic
                        bare = re.sub(r"\(.*\)", "", p).strip()
                        # take last token
                        name = bare.split()[-1]
                        results.append(exp.Column(name.strip(), table=None))
        else:
            # return empty for other classes
            pass
        return results


def parse_one(sql: str, dialect: str = None):
    return SimpleTree(sql)
