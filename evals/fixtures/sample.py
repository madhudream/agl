"""A frozen file for eval tasks. Do not edit: tasks pin counts to it (7 def lines, 2 classes)."""


class Account:
    def __init__(self, owner, balance=0):
        self.owner = owner
        self.balance = balance

    def deposit(self, amount):
        self.balance += amount
        return self.balance

    def withdraw(self, amount):
        if amount > self.balance:
            raise ValueError("insufficient funds")
        self.balance -= amount
        return self.balance


class Ledger:
    def __init__(self):
        self.entries = []

    def record(self, account, amount):
        def fmt(a):
            return f"{a.owner}:{amount}"
        self.entries.append(fmt(account))


def total(accounts):
    return sum(a.balance for a in accounts)
