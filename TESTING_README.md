# MeshCtx Project Test Suite

This directory contains the test suite for the MeshCtx project.

## Running Tests

1. Make sure you have Python 3.8 or higher installed.
2. Install the required dependencies:
   ```bash
   pip install pytest
   ```
3. Run all tests:
   ```bash
   python run_tests.py
   ```
4. To run only unit tests:
   ```bash
   python -m unittest tests/unit/test_*.py
   ```
5. To run only integration tests:
   ```bash
   python -m unittest tests/integration/test_*.py
   ```

## Test Coverage

The current test suite includes:
- Unit tests for MemoryEngine initialization
- Integration tests for Message storage, embedding, and extraction

Future improvements:
- Add more comprehensive unit tests for each component
- Implement coverage reporting
- Add CI/CD integration for automated testing

For more information about the MeshCtx project, see the main README.md file in the project root.