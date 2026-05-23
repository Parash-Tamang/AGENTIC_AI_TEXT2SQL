class Table:
    def __init__(self, name, alias=None, db=None, schema=None):
        self.name = name
        self.alias = alias
        self.args = {"db": db, "schema": schema}


class Column:
    def __init__(self, name, table=None):
        self.name = name
        self.table = table


class Alias:
    def __init__(self, name):
        self.name = name


class CTE:
    def __init__(self, alias):
        self.args = {"alias": alias}


class Select:
    pass


class Order:
    pass


class Group:
    pass


class Anonymous:
    def __init__(self, name):
        self.name = name


# Aggregates
class Sum:
    pass


class Count:
    pass


class Avg:
    pass


class Min:
    pass


class Max:
    pass
