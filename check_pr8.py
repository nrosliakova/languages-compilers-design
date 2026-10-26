import subprocess
import sys
import unittest
from pathlib import Path

from src.compiler import (
    AstPrinter, CodeGenerator, LambdaNode, Parser, SemanticChecker, load_program,
)
from src.lexer import lex


ROOT = Path(__file__).resolve().parent


def checked(name):
    program = load_program(ROOT / 'tests' / 'ok' / name)
    SemanticChecker().check(program)
    return program


class Practice8Checks(unittest.TestCase):
    def test_raw_ast_keeps_lambda(self):
        program = load_program(ROOT / 'tests/ok/pr8_lambda_task2.txt')
        node = next(item for item in program.statements if isinstance(item, LambdaNode))
        self.assertIsNone(node.lowered_struct)
        text = program.accept(AstPrinter())
        self.assertIn('Lambda add_k -> i32', text)
        self.assertIn('Capture k', text)
        self.assertNotIn('Struct lambda.add_k', text)

    def test_checked_ast_shows_lowering(self):
        program = checked('pr8_lambda_task2.txt')
        node = next(item for item in program.statements if isinstance(item, LambdaNode))
        self.assertEqual(node.lowered_struct.fields[0].name, 'k')
        self.assertFalse(node.lowered_struct.fields[0].mutable)
        self.assertEqual(node.lowered_struct.methods[0].name, 'call')
        text = program.accept(AstPrinter())
        self.assertIn('Struct lambda.add_k', text)
        self.assertIn('Decl add_k lambda.add_k const', text)
        self.assertIn('CallableCall add_k', text)

    def test_captured_lambda_keeps_its_type(self):
        program = checked('pr8_lambda_capture_lambda.txt')
        first, second = [item for item in program.statements if isinstance(item, LambdaNode)]
        self.assertEqual(
            second.lowered_struct.fields[0].type_name, first.declaration.type_name,
        )
        self.assertIs(second.declaration.init.values[0].decl, first.declaration)

    def test_repeated_names_have_unique_internal_types(self):
        program = checked('pr8_lambda_same_names.txt')
        self.assertEqual(
            [item.name for item in program.generated_structs],
            ['lambda.same', 'lambda.same.2'],
        )

    def test_llvm_contains_struct_method_and_capture_store(self):
        module = CodeGenerator().generate(checked('pr8_lambda_task2.txt'))
        text = str(module)
        self.assertIn('%"lambda.add_k" = type {i32}', text)
        self.assertIn('define i32 @"lambda.add_k_call"', text)
        self.assertIn('alloca %"lambda.add_k"', text)
        self.assertIn('getelementptr %"lambda.add_k"', text)
        self.assertIn('store i32 %"k.value"', text)

    def test_ast_flags_run_different_phases(self):
        source = ROOT / 'tests/err/pr8_lambda_missing_capture.txt'
        for flag, expected_code in [('--ast', 0), ('--ast-checked', 1)]:
            result = subprocess.run(
                [sys.executable, str(ROOT / 'src/compiler.py'), flag, str(source)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, expected_code, result.stderr)
            if flag == '--ast':
                self.assertIn('Lambda add', result.stdout)
            else:
                self.assertIn('not captured', result.stderr)

    def test_task1_forms_still_generate_identical_ir(self):
        prefix = '''struct Scale
{
    i32 k
    fn call := (i32 v) -> i32
    {
        i32 r{v * k}
        exit r
    }
}
Scale triple{3}
'''
        modules = []
        for expression in ['triple(14)', 'triple.call(14)']:
            program = Parser(lex((prefix + 'exit ' + expression + '\n').encode())).parse_program()
            SemanticChecker().check(program)
            modules.append(str(CodeGenerator().generate(program)))
        self.assertEqual(*modules)

    def test_mutable_capture_lowering_and_propagation(self):
        program = load_program(ROOT / 'tests/ok/pr8_mut_bonus.txt')
        lambdas = [item for item in program.statements if isinstance(item, LambdaNode)]
        self.assertTrue(lambdas[0].captures[0].mutable)
        self.assertIn('Capture mut n', program.accept(AstPrinter()))
        SemanticChecker().check(program)
        for node in lambdas:
            self.assertTrue(node.lowered_struct.fields[0].mutable)
            self.assertTrue(node.declaration.mutable)
            self.assertTrue(node.lowered_struct.methods[0].mutating)
        text = program.accept(AstPrinter())
        self.assertIn('Field next lambda.next mut', text)
        self.assertIn('Decl next lambda.next mut', text)

    def test_mutable_capture_without_writes_is_not_mutating(self):
        program = checked('pr8_mut_pure_const_copy.txt')
        value, wrapper = [
            item for item in program.statements if isinstance(item, LambdaNode)
        ]
        self.assertTrue(value.declaration.mutable)
        self.assertFalse(value.lowered_struct.methods[0].mutating)
        self.assertFalse(wrapper.declaration.mutable)
        self.assertFalse(wrapper.lowered_struct.methods[0].mutating)


if __name__ == '__main__':
    unittest.main()
