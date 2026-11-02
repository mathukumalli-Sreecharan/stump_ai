def solve(values):
    if not values:
        return True
    prev = values[0]
    for num in values[1:]:
        if num != prev + 1:
            return False
        prev = num
    return True
