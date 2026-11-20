import unittest

from game_guides import get_game_guide


class MethSystemOneGuideTests(unittest.TestCase):
    def test_question_variants_match(self):
        for query in (
            "!How to cook meth",
            "how to cook meth",
            "Meth System 1",
            "meth system one",
            "meth cooking",
        ):
            with self.subTest(query=query):
                self.assertIsNotNone(get_game_guide(query))

    def test_guide_contains_correct_postals(self):
        guide = get_game_guide("!How to cook meth")
        combined = " ".join([guide["description"], *(value for _, value in guide["fields"])])
        for postal in ("4013", "3024", "2060", "10065", "10066", "3043", "3048", "4024"):
            with self.subTest(postal=postal):
                self.assertIn(postal, combined)

    def test_guide_does_not_match_unrelated_questions(self):
        self.assertIsNone(get_game_guide("where is the hidden shed"))
        self.assertIsNone(get_game_guide("how to cook dinner"))


if __name__ == "__main__":
    unittest.main()
