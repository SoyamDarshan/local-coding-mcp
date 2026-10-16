"""Fixture repo and test cases for scripts/live_check.py (kept separate so each file stays small)."""

from __future__ import annotations

from dataclasses import dataclass, field

PRICING = '''"""Pricing helpers."""


def apply_discount(price: float, pct: float) -> float:
    """Return price after a percentage discount."""
    return round(price * (1 + pct / 100), 2)


def total(items: list[tuple[str, float, int]]) -> float:
    """Sum of price * quantity for (sku, price, qty) items."""
    return round(sum(price * qty for _sku, price, qty in items), 2)


class Cart:
    def __init__(self) -> None:
        self.items: dict[str, tuple[float, int]] = {}

    def add(self, sku: str, price: float, qty: int = 1) -> None:
        if qty <= 0:
            raise ValueError("qty must be positive")
        old = self.items.get(sku, (price, 0))
        self.items[sku] = (price, old[1] + qty)

    def count(self) -> int:
        return sum(q for _p, q in self.items.values())
'''

TEST_PRICING = '''from shop.pricing import Cart, apply_discount, total


def test_discount():
    assert apply_discount(200.0, 10) == 180.0


def test_total():
    assert total([("a", 2.5, 2), ("b", 1.0, 1)]) == 6.0


def test_cart_count():
    cart = Cart()
    cart.add("a", 1.0, 2)
    cart.add("a", 1.0, 1)
    assert cart.count() == 3
'''

BUTTON = '''import React from "react";

type ButtonProps = { label: string; onClick: () => void };

export const Button = ({ label, onClick }: ButtonProps) => {
  return (
    <button className="btn" onClick={onClick}>
      {label}
    </button>
  );
};

export function Icon() {
  return <span>*</span>;
}
'''


def big_module() -> str:
    return "".join(f"def func_{i}(x: int) -> int:\n    return x + {i}\n\n\n" for i in range(110))


def report_module() -> str:
    lines = ["def summary(orders: list[dict]) -> dict:", '    """Aggregate order stats."""', "    out: dict = {}"]
    lines += [f'    out["f{i}"] = sum(o.get("f{i}", 0) for o in orders)' for i in range(44)]
    return "\n".join([*lines, '    out["count"] = len(orders)', "    return out", ""])


def files() -> dict[str, str]:
    return {
        "shop/__init__.py": "",
        "shop/pricing.py": PRICING,
        "shop/big.py": big_module(),
        "shop/report.py": report_module(),
        "tests/test_pricing.py": TEST_PRICING,
        "web/Button.tsx": BUTTON,
    }


@dataclass
class Case:
    id: str
    title: str
    spec: str
    files_to_edit: list[str]
    verify: str  # python code run in the repo; must exit 0 when the result is right
    checks: list[str] = field(default_factory=lambda: ["compile"])
    symbols: list[str] | None = None
    expect: str = "passed"
    budget: int | None = None  # prompt_budget_tokens override


CASES = [
    Case("fix-bug", "fix a wrong sign in apply_discount",
         "In shop/pricing.py, apply_discount adds the percentage instead of subtracting it. "
         "Fix it so apply_discount(200.0, 10) == 180.0. Change nothing else.",
         ["shop/pricing.py"], "from shop.pricing import apply_discount as f; assert f(200.0, 10) == 180.0",
         checks=["compile", "pytest"]),
    Case("add-function", "add a typed helper function",
         "In shop/pricing.py add `def tax(amount: float, rate: float = 0.18) -> float` returning the tax "
         "on amount, rounded to 2 decimals. Add it after total(). Do not change other code.",
         ["shop/pricing.py"], "from shop.pricing import tax; assert tax(100.0) == 18.0 and tax(10.0, 0.05) == 0.5"),
    Case("add-method", "add a method to a class",
         "In shop/pricing.py add method `remove(self, sku: str) -> None` to class Cart. It deletes the "
         "sku from self.items and raises KeyError if the sku is not in the cart.",
         ["shop/pricing.py"],
         "from shop.pricing import Cart\nc = Cart(); c.add('a', 1.0)\nc.remove('a'); assert c.count() == 0\n"
         "try:\n    c.remove('a')\nexcept KeyError:\n    pass\nelse:\n    raise SystemExit(1)"),
    Case("new-files", "create a module and its test",
         "Create shop/slug.py with `def slugify(text: str) -> str`: lowercase, strip, replace runs of "
         "non-alphanumeric characters with a single '-', and trim leading/trailing '-'. Create "
         "tests/test_slug.py with 3 pytest tests for it (e.g. 'Hello, World!' -> 'hello-world').",
         ["shop/slug.py", "tests/test_slug.py"],
         "from shop.slug import slugify as s; assert s('Hello, World!') == 'hello-world' and s('  A  b ') == 'a-b'",
         checks=["compile", "pytest"]),
    Case("big-file-symbols", "edit one function in a file shown as an excerpt",
         "In shop/big.py change func_42 so it returns x * 42 instead of x + 42. Change nothing else.",
         ["shop/big.py"], "from shop.big import func_42, func_43; assert func_42(2) == 84 and func_43(2) == 45",
         symbols=["shop/big.py::func_42"], budget=1500),
    Case("standards-loop", "add a field to a 48-line function (standards must be respected)",
         'In shop/report.py, summary() must also return out["avg_f0"]: out["f0"] divided by the number '
         "of orders, or 0 when there are no orders. Keep every function at most 50 lines.",
         ["shop/report.py"],
         "from shop.report import summary\nr = summary([{'f0': 2}, {'f0': 4}]); assert r['avg_f0'] == 3 and summary([])['avg_f0'] == 0",
         symbols=["shop/report.py::summary"]),
    Case("ambiguous-spec", "ambiguous spec should produce BLOCKED, not a guess",
         "Round the discount in apply_discount using the store's configured rounding mode.",
         ["shop/pricing.py"], "raise SystemExit(0)", expect="blocked"),
    Case("tsx-excerpt", "add an optional prop to a React component",
         "In web/Button.tsx add an optional prop `disabled?: boolean` to ButtonProps and pass it to the "
         "<button> element as disabled={disabled}.",
         ["web/Button.tsx"],
         "t = open('web/Button.tsx', encoding='utf-8').read(); assert 'disabled?: boolean' in t and 'disabled={disabled}' in t",
         symbols=["web/Button.tsx::Button"]),
]
