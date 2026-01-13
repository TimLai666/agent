#!/usr/bin/env python3
"""
Module Template

A template for creating well-structured Python modules.
"""

from typing import List, Dict, Optional


class MyClass:
    """Example class with proper structure."""

    def __init__(self, name: str, value: int = 0):
        """
        Initialize MyClass.

        Args:
            name: The name of the instance
            value: Optional initial value (default: 0)
        """
        self.name = name
        self.value = value

    def process(self, data: List[int]) -> Dict[str, int]:
        """
        Process data and return results.

        Args:
            data: List of integers to process

        Returns:
            Dictionary with processing results
        """
        return {
            "sum": sum(data),
            "count": len(data),
            "max": max(data) if data else 0
        }


def main():
    """Main function."""
    obj = MyClass("example", 42)
    result = obj.process([1, 2, 3, 4, 5])
    print(f"Results: {result}")


if __name__ == "__main__":
    main()
