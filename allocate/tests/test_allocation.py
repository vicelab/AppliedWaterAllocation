import unittest

from allocate import load


class AllocationTests(unittest.TestCase):

    def setUp(self) -> None:
        load.load()

    def test_run_allocation(self):
        self.assertEqual(True, False)


if __name__ == '__main__':
    unittest.main()
