from compiler import CodeGenerator, SemanticChecker, load_program
import llvmlite.binding as llvm

for path in [
    "tests/manual/pr5_not.txt",
    "tests/manual/pr5_slots.txt",
]:
    program = load_program(path)
    SemanticChecker().check(program)

    generator = CodeGenerator()
    module = generator.generate(program)

    llvm.parse_assembly(str(module)).verify()

    seen_other_instruction = False

    for block in generator.main.blocks:
        for instruction in block.instructions:
            if instruction.opname == "alloca":
                assert block is generator.main.entry_basic_block
                assert not seen_other_instruction
            elif block is generator.main.entry_basic_block:
                seen_other_instruction = True

    print(f"PASS: valid LLVM and entry-first allocations — {path}")
