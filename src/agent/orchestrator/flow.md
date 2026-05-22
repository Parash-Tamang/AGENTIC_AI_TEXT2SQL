Node: query_refiner
Reads from state: ["user_query", "history", "retry_feedback"]
Writes to state: ["construct", "refined_query"]
Router: None
Router returns: None

Node: intent_classifier_node
Reads from state: ["construct", "domain_context"] 
Writes to state: ["intent"]
Router: None
Router returns: None

Node: query_decomposer
Reads from state: ["construct", "domain_context"]
Writes to state: ["decomposed"]
Router: intent_router
Router returns: ["schema_fetcher", "views_fetcher", "response"]

Node: views_fetcher_node
Reads from state: ["construct", "decomposed"]
Writes to state: ["views", "views_grade", "view_suggestions"]
Router: None
Router returns: None

Node: schema_fetcher_node
Reads from state: ["construct", "decomposed", "views_grade"]
Writes to state: ["schemas", "retrieved_schemas", "seed_tables", "join_paths", "schema_coverage", "schema_coverage_history"]
Router: None
Router returns: None

Node: sql_generator_node
Reads from state: ["construct", "user_query", "retrieved_schemas", "seed_tables", "join_paths"]
Writes to state: ["generated_sql", "token_count", "token_breakdown", "sql_errors", "hallucinated_tables"]
Router: None
Router returns: None

Node: sql_validator_node
Reads from state: ["generated_sql", "construct", "user_query", "retrieved_schemas", "seed_tables", "join_paths"]
Writes to state: ["validation_result", "validation_passed", "validation_errors", "suggested_fix"]
Router: sql_validation_router
Router returns: ["sql_generator", "results_validator"]

Node: sql_post_execution_validator_node
Reads from state: ["user_query", "generated_sql", "retrieved_schemas", "join_paths", "validation_structural", "execution_result"]
Writes to state: ["execution_analysis", "validation_with_llm", "self_rag_decision", "validation_token_breakdown", "validation_error"]
Router: validation_router
Router returns: ["sql_generator", "query_refiner", "response"]

Node: response_generator_node
Reads from state: ["user_query", "generated_sql", "execution_result", "validation_with_llm", "intent"]
Writes to state: ["user_facing_response", "response_token_breakdown", "response_error"]
Router: None
Router returns: None

Node: executor (Tool / Service Interface)
Reads from state: ["generated_sql"]
Writes to state: ["execution_result"]
Router: None
Router returns: None