# Compiler and runtime messages for the 0.3.1 tests

Demo code, no real data. Written on a developer Mac on 18 November 2026 and read by `tests/test_audit_031.py`.

- `javac-*.txt`: javac 21.0.13 compiling the base of a tiny Java shop together with a new test that uses a new class (`Discount`), a new method without an access word (`withTax`) and a new constant (`MAX_QUANTITY`). The folder of the throwaway project was taken out of the paths.
- `node-*.txt`: node 22.18.0 calling a class method and an exported function that do not exist yet.
