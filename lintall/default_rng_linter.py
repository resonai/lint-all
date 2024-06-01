from typing import TYPE_CHECKING

from astroid import nodes

from pylint.checkers import BaseChecker
from pylint.checkers.utils import check_messages
from pylint.interfaces import IAstroidChecker

if TYPE_CHECKING:
    from pylint.lint import PyLinter


class DefaultRNGUnseededChecker(BaseChecker):

    __implements__ = (IAstroidChecker,)
    name = "no_unseeded_default_rng_allowed"
    msgs = {
        "W5999": (
            "unseeded default_rng()",
            "default-rng-used-with-no-args",
            "Calling default_rng with no see violates our seeding procedures "
            "and will result in non-reproducible tests",
        )
    }

    @check_messages("default-rng-used-with-no-args")
    def visit_call(self, node: nodes.Call) -> None:
        func = node.func
        default_rng_call = False
        if isinstance(node.func, nodes.node_classes.Attribute):
            if func.attrname == "default_rng":
                default_rng_call = True
        elif isinstance(node.func, nodes.node_classes.Name):
            if func.name == "default_rng":
                default_rng_call = True
        if default_rng_call and node.args == []:
            self.add_message("default-rng-used-with-no-args", node=node)
        # else:
        #   print(f'No: {node.attrname}')


def register(linter: "PyLinter") -> None:
    linter.register_checker(DefaultRNGUnseededChecker(linter))
