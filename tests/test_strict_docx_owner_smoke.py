import unittest

from tools import strict_docx_owner_smoke


class StrictDocxOwnerSmokeTest(unittest.TestCase):
    def test_smoke_admits_then_revokes_without_exposing_raw_fixture_content(self):
        report = strict_docx_owner_smoke.run_smoke()

        self.assertEqual(report["backend"], "sqlite-temporary")
        self.assertEqual(report["provider_calls"], 0)
        self.assertTrue(report["admission"]["admitted"])
        self.assertTrue(report["admission"]["job_id"])
        self.assertEqual(report["admission"]["work_unit_count"], 1)
        self.assertTrue(report["approval"]["approval_id"])
        self.assertTrue(report["approval"]["custody_id"])
        self.assertRegex(
            report["approval"]["snapshot_digest_prefix"], r"^[0-9a-f]{12}$"
        )
        self.assertFalse(report["after_revocation"]["admitted"])
        self.assertEqual(report["after_revocation"]["denial_code"], "approval_revoked")
        self.assertNotIn("synthetic strict source", str(report).lower())
        self.assertNotIn("approved-snapshot", str(report))


if __name__ == "__main__":
    unittest.main()
