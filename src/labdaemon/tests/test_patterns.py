#!/usr/bin/env python
"""Test script for labdaemon.patterns module."""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))


def test_server_api():
    """Test ServerAPI class."""
    from labdaemon.server import ServerAPI
    
    api = ServerAPI("http://localhost:5000")
    assert api.base_url == "http://localhost:5000"
    
    print("✓ ServerAPI initialization tests passed")


def test_ensure_server():
    """Test ensure_server function."""
    from labdaemon.patterns import ensure_server
    
    # Test with non-existent server (should return False quickly)
    assert not ensure_server("nonexistent", timeout=0.1)
    assert not ensure_server(server_url="http://localhost:9999", timeout=0.1)
    
    print("✓ ensure_server tests passed")


def test_imports():
    """Test that patterns can be imported from main module."""
    import labdaemon as ld
    
    # Check if patterns are available
    # Note: SetupRegistry has been removed from the patterns module
    # according to the new server management design
    assert hasattr(ld, 'ensure_server')
    assert hasattr(ld, 'ensure_device')
    
    print("✓ Pattern imports from main module work")


def main():
    """Run all tests."""
    print("Testing labdaemon.patterns module...")
    print()
    
    try:
        test_server_api()
        test_ensure_server()
        test_imports()
        
        print()
        print("All tests passed! ✓")
        
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()