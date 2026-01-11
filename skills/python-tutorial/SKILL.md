---
name: python-tutorial
description: Python programming tutorial and best practices. Use when the user asks about Python basics, syntax, or wants to learn Python programming.
---

# Python Tutorial Skill

This skill provides Python programming guidance and includes bundled resources for learning.

## When to Use

- User wants to learn Python basics
- User asks about Python syntax or features
- User needs Python code examples
- User wants to understand Python best practices

## Core Concepts

### 1. Variables and Types

```python
# Basic types
name = "Alice"           # str
age = 25                # int
height = 1.75           # float
is_student = True       # bool

# Collections
numbers = [1, 2, 3]     # list
coords = (10, 20)       # tuple
unique_ids = {1, 2, 3}  # set
person = {"name": "Bob", "age": 30}  # dict
```

### 2. Control Flow

```python
# If statements
if age >= 18:
    print("Adult")
elif age >= 13:
    print("Teenager")
else:
    print("Child")

# Loops
for num in range(5):
    print(num)

while condition:
    # do something
    pass
```

### 3. Functions

```python
def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"

# Lambda functions
square = lambda x: x ** 2
```

### 4. Classes

```python
class Person:
    def __init__(self, name: str, age: int):
        self.name = name
        self.age = age

    def greet(self) -> str:
        return f"Hi, I'm {self.name}"
```

## Best Practices

1. **Use Type Hints**: Makes code more readable and catches errors
2. **Follow PEP 8**: Python's style guide
3. **Write Docstrings**: Document functions and classes
4. **Use List Comprehensions**: More Pythonic than loops
5. **Handle Exceptions**: Use try/except appropriately

## Available Resources

This skill includes bundled resources:

- **Scripts**: Example Python scripts demonstrating concepts
- **References**: Additional documentation and cheat sheets
- **Assets**: Templates and starter code

To access resources, mention you want to see examples or reference materials.
