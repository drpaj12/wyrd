import json
import unittest

from wyrd import report


def run(
    design: str = "d",
    arch: str = "k6",
    recipe: str = "r",
    params: dict[str, object] | None = None,
    started: str = "1",
    status: str = "ok",
    **metrics: float,
) -> dict[str, object]:
    return {
        "key": f"{design}{arch}{recipe}{started}{params}",
        "design": design,
        "arch": arch,
        "recipe": recipe,
        "params": json.dumps(params or {}, sort_keys=True),
        "status": status,
        "started": started,
        "ended": None,
        "run_dir": "x",
        **metrics,
    }


class NumberTest(unittest.TestCase):
    def test_formats(self) -> None:
        cases = {
            10: "10",
            12345.6: "12346",
            0.000015: "0.000015",
            1.23456: "1.235",
            4.56789: "4.568",
            0.5: "0.5",
            -2.34567: "-2.346",
            1e-7: "0.0000001",
            1e20: "100000000000000000000",
        }
        for value, text in cases.items():
            self.assertEqual(report.number(value), text, value)
        self.assertEqual(report.number(None), "")


class TableTest(unittest.TestCase):
    def test_one_row_per_params_and_param_columns(self) -> None:
        rows = [
            run(params={"seed": 2, "eff": "hi"}, luts=2),
            run(params={"seed": 1, "eff": "hi"}, luts=1),
            run(params={"seed": 1, "eff": "hi"}, started="0", luts=9),  # older, collapses
        ]
        t = report.table(rows)
        self.assertEqual(t[0], ["design", "arch", "eff", "seed", "status", "luts"])
        self.assertEqual(
            t[1:], [["d", "k6", "hi", "1", "ok", "1"], ["d", "k6", "hi", "2", "ok", "2"]]
        )

    def test_recipe_column_only_with_several_recipes(self) -> None:
        self.assertNotIn("recipe", report.table([run(luts=1)])[0])
        t = report.table([run(recipe="a", luts=1), run(recipe="b", luts=2)])
        self.assertEqual(t[0], ["design", "arch", "recipe", "status", "luts"])
        self.assertEqual(len(t), 3)

    def test_md_escapes_pipe(self) -> None:
        out = report.render_md([["a|b", "c"], ["x|y", "z"]])
        self.assertEqual(out.splitlines()[0], "| a\\|b | c |")
        self.assertEqual(out.splitlines()[2], "| x\\|y | z |")


class CompareTest(unittest.TestCase):
    def test_match_on_full_identity(self) -> None:
        a = [run(params={"s": 1}, luts=10), run(params={"s": 2}, luts=20)]
        b = [run(params={"s": 1}, luts=12), run(params={"s": 3}, luts=5)]
        c = report.compare(a, b, ["luts"])
        self.assertEqual(c[0], ["design", "arch", "s", "metric", "A", "B", "B/A"])
        self.assertEqual(c[1:], [["d", "k6", "1", "luts", "10", "12", "1.2"]])
        self.assertEqual(
            report.unmatched(a, b),
            [
                'only in A: d k6 r {"s": 2}',
                'only in B: d k6 r {"s": 3}',
            ],
        )

    def test_only_metrics_present_on_a_side(self) -> None:
        a = [run(luts=10, ffs=1)]
        b = [run(luts=12, depth=3)]
        names = [r[2] for r in report.compare(a, b, ["luts", "ffs", "depth", "none"])[1:]]
        self.assertEqual(names, ["luts", "ffs", "depth"])
