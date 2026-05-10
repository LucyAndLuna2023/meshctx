#!/usr/bin/env python3
import unittest
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Discover and run all tests
if __name__ == '__main__':
    # Run unit tests
    print("Running unit tests...")
    loader = unittest.TestLoader()
    suite = loader.discover('tests/unit', pattern='test_*.py')
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Run integration tests
    print("\nRunning integration tests...")
    suite = loader.discover('tests/integration', pattern='test_*.py')
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Exit with error code if any tests failed
    sys.exit(0 if result.wasSuccessful() else 1)