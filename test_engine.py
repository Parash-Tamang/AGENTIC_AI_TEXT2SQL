import asyncio
import logging

logging.basicConfig(level=logging.DEBUG)

from src.agent.orchestrator.engine import GraphEngine
from src.agent.orchestrator.topology import GRAPH, ROUTERS, START_NODE, END_NODES
from src.agent.orchestrator.engine import ROUTER_FNS

# Mock Nodes
async def m_query_refiner(state):
    state['visited'].append('query_refiner')
    return state

async def m_intent_classifier(state):
    state['visited'].append('intent_classifier')
    state['intent'] = {'route_to': 'QueryTranslation'}
    return state

async def m_query_decomposer(state):
    state['visited'].append('query_decomposer')
    return state

async def m_views_fetcher(state):
    state['visited'].append('views_fetcher')
    return state

async def m_schema_fetcher(state):
    state['visited'].append('schema_fetcher')
    return state

async def m_sql_generator(state):
    state['visited'].append('sql_generator')
    return state

async def m_sql_validator(state):
    state['visited'].append('sql_validator')
    state['validation_passed'] = True  # Pass validation
    return state

async def m_executor(state):
    state['visited'].append('executor')
    return state

async def m_sql_post_execution_validator(state):
    state['visited'].append('sql_post_execution_validator')
    state['validation_passed'] = True
    state['self_rag_decision'] = {'self_rag_retry': False}
    return state

async def m_response_generator(state):
    state['visited'].append('response_generator')
    return state

mock_nodes = {
    'query_refiner': m_query_refiner,
    'intent_classifier': m_intent_classifier,
    'query_decomposer': m_query_decomposer,
    'views_fetcher': m_views_fetcher,
    'schema_fetcher': m_schema_fetcher,
    'sql_generator': m_sql_generator,
    'sql_validator': m_sql_validator,
    'executor': m_executor,
    'sql_post_execution_validator': m_sql_post_execution_validator,
    'response_generator': m_response_generator,
}

async def run_test():
    engine = GraphEngine(
        nodes=mock_nodes,
        graph=GRAPH,
        routers=ROUTER_FNS,
        start_node=START_NODE,
        end_nodes=END_NODES
    )
    initial_state = {'visited': []}
    final_state = await engine.run(initial_state)
    print('\n---> FINAL STATE VISITED:', final_state['visited'])

if __name__ == '__main__':
    asyncio.run(run_test())
