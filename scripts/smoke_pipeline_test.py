import json
import traceback

from src.agent.nodes.sql_validator import sql_validator_node
from src.agent.nodes.rbac_enforcer import rbac_enforcer_node

# Use DummyLLM for deterministic local testing


# Dummy LLM that returns a benign semantic validation
class DummyLLM:
    def generate(
        self,
        system_prompt=None,
        user_prompt=None,
        response_format=None,
        json_mode=False,
        **kwargs
    ):
        # Return a dict matching expected LLM validator output
        return {
            "valid": True,
            "retry": False,
            "score": 1,
            "reasoning": "OK",
            "concept_gaps": [],
            "critical_issues": [],
            "warnings": [],
            "suggested_fix": "",
        }


llm = DummyLLM()


# Minimal schema for SalesLT.Customer
schemas = [
    {
        "schema_name": "SalesLT",
        "table_name": "Customer",
        "columns": [
            {"name": "CustomerID", "type": "int"},
            {"name": "FirstName", "type": "nvarchar"},
        ],
    }
]


# Case A: generated SQL missing mandatory filter (should return authorization_policy)
state_missing = {
    "generated_sql": "SELECT * FROM SalesLT.Customer",
    "construct": "Get customer details",
    "retrieved_schemas": schemas,
    "seed_tables": ["SalesLT.Customer"],
    "join_paths": [],
    "mandatory_filters": {
        "SalesLT.Customer": {"CustomerID": {"filter": "id", "values": ["20"]}}
    },
    "allowed_tables": ["SalesLT.Customer"],
    "retry_count": 0,
}


# Case B: generated SQL includes mandatory filter (should pass)
state_ok = dict(state_missing)
state_ok["generated_sql"] = "SELECT * FROM SalesLT.Customer WHERE CustomerID=20"


def run_case(name, state):
    print("---")
    print("Running:", name)
    try:
        validated = sql_validator_node(llm=llm, state=state)
        print("Validator output (summary):")
        print(
            json.dumps(
                {
                    "validation_passed": validated.get("validation_passed"),
                    "validation_result_needs_retry": validated.get(
                        "validation_result", {}
                    ).get("needs_retry"),
                    "authorization_policy": validated.get("authorization_policy"),
                },
                indent=2,
            )
        )

        enforced = rbac_enforcer_node(validated)
        print("RBAC enforcer output (summary):")
        print(
            json.dumps(
                {
                    "rbac_denied": enforced.get("rbac_denied"),
                    "permission_denied": enforced.get("permission_denied"),
                    "validation_passed": enforced.get("validation_passed"),
                    "authorization_policy": enforced.get("authorization_policy"),
                    "retry_feedback": enforced.get("retry_feedback"),
                },
                indent=2,
            )
        )
    except Exception:
        traceback.print_exc()


if __name__ == "__main__":
    run_case("missing_filter", state_missing)
    run_case("with_filter", state_ok)
    print("---\nSmoke test complete")
