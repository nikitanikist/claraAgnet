from clara.portal_usage import portal_usage


def test_unknown_model_usage_is_not_zero_or_complete():
    result = portal_usage({'version': 2, 'coverage': 'unavailable', 'tokens': {}},
                          wall_seconds=26.1, waiting_seconds=12.0)
    assert result['input_tokens'] is None and result['output_tokens'] is None
    assert result['estimated_cost_usd'] is None
    assert result['usage_coverage'] == 'unknown'
    assert result['active_seconds'] + result['waiting_seconds'] == 27
    assert portal_usage(None, wall_seconds=27, waiting_seconds=12)['usage_coverage'] == 'unknown'


def test_partial_observations_preserve_known_tokens_without_invented_cost():
    result = portal_usage({'version': 2, 'coverage': 'partial', 'tokens': {
        'input_tokens': 1100, 'output_tokens': None, 'cache_read_input_tokens': 700,
        'cache_creation_input_tokens': 200}}, wall_seconds=30, waiting_seconds=0)
    assert result['input_tokens'] == 1100 and result['cache_tokens'] == 900
    assert result['output_tokens'] is None and result['estimated_cost_usd'] is None
    assert result['usage_coverage'] == 'partial'


def test_reported_zero_is_valid_but_unknown_price_stays_unknown():
    raw = {'version': 2, 'coverage': 'reported', 'tokens': {'input_tokens': 0, 'output_tokens': 0,
           'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}, 'sdk_estimated_usd': 0}
    assert portal_usage(raw, wall_seconds=1, waiting_seconds=0)['usage_coverage'] == 'complete'
    raw['unknown_price'] = True
    result = portal_usage(raw, wall_seconds=1, waiting_seconds=0)
    assert result['estimated_cost_usd'] is None and result['usage_coverage'] == 'partial'
