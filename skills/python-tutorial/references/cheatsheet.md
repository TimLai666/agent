# Python Quick Reference

## Common Operations

### Lists
```python
# Create
my_list = [1, 2, 3]

# Append
my_list.append(4)

# Slice
my_list[1:3]  # [2, 3]

# Comprehension
squares = [x**2 for x in range(5)]
```

### Dictionaries
```python
# Create
person = {"name": "Alice", "age": 30}

# Access
person["name"]
person.get("email", "default@example.com")

# Update
person["age"] = 31
person.update({"email": "alice@example.com"})
```

### String Operations
```python
# Formatting
f"Hello, {name}!"
"Hello, {}!".format(name)

# Methods
text.lower()
text.upper()
text.strip()
text.split(",")
",".join(items)
```

### File I/O
```python
# Read
with open("file.txt", "r") as f:
    content = f.read()

# Write
with open("output.txt", "w") as f:
    f.write("Hello, World!")
```
