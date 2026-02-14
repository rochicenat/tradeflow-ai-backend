# Read the file
with open('main.py', 'r') as f:
    content = f.read()

# Remove duplicate Analysis class and endpoints at the end
lines = content.split('\n')

# Find where the duplicate starts (after "if __name__")
clean_lines = []
found_main = False
for line in lines:
    if 'from database import User' in line and found_main:
        break
    clean_lines.append(line)
    if 'if __name__ == "__main__":' in line:
        found_main = True

# Write clean version
with open('main.py', 'w') as f:
    f.write('\n'.join(clean_lines))

print("Fixed!")
