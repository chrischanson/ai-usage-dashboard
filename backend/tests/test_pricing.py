import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pricing import estimate_claude_cost


class TestEstimateClaudeCost(unittest.TestCase):
    def test_known_model_input_and_output(self):
        # claude-opus-4-8: $5/Mtok input, $25/Mtok output
        cost = estimate_claude_cost('claude-opus-4-8', 1_000_000, 1_000_000)
        self.assertAlmostEqual(cost, 5.00 + 25.00)

    def test_cache_read_and_write_multipliers(self):
        cost = estimate_claude_cost(
            'claude-opus-4-8', 0, 0, cache_read=1_000_000, cache_write=1_000_000)
        self.assertAlmostEqual(cost, 5.00 * 0.1 + 5.00 * 1.25)

    def test_unknown_model_is_zero_not_a_guess(self):
        cost = estimate_claude_cost('claude-3-nonexistent', 1_000_000, 1_000_000)
        self.assertEqual(cost, 0.0)

    def test_zero_tokens_is_zero(self):
        self.assertEqual(estimate_claude_cost('claude-sonnet-5', 0, 0), 0.0)


if __name__ == '__main__':
    unittest.main()
