import unittest

from gridgpu.reporting import summarize


class ReportingTests(unittest.TestCase):
    def test_summary_counts_compliance_and_energy(self):
        records = [
            {"type": "sample", "facility_power_watts": 900, "envelope_watts": 1000},
            {"type": "sample", "facility_power_watts": 1100, "envelope_watts": 1000},
            {"type": "action"},
        ]
        result = summarize(records, sample_seconds=1)
        self.assertEqual(result.sample_count, 2)
        self.assertEqual(result.compliant_samples, 1)
        self.assertEqual(result.compliance_ratio, 0.5)
        self.assertEqual(result.maximum_exceedance_watts, 100)
        self.assertAlmostEqual(result.energy_over_limit_wh, 100 / 3600)
        self.assertEqual(result.action_count, 1)

    def test_empty_summary_is_compliant(self):
        result = summarize([])
        self.assertEqual(result.compliance_ratio, 1.0)


if __name__ == "__main__":
    unittest.main()
