def reverse(head):
    perv = None
    curr = head
    while curr is not None:
        nxt = curr.next
        curr.next = perv
        perv = curr
        curr = nxt
    return perv

def is_valid(s): 
    stack = []
    mapping = {')': '(', ']': '[', '}': '{'}
    for char in '([{':
        if char in mapping:
            stack.append(char)
        else:
            if not stack or mapping(char) != stack.pop():
                return False
        return len(stack) == 0

def two_sum(nums, target):
    seen = {}
    for i,v in enumerate(nums):
        if target - v in seen:
            return [seen[target - v], i]
        seen[v] = i
    return []

def search_insert(nums, target):
    left, right = 0, len(nums) - 1
    while left <= right:
        mid = (left + right) // 2
        if nums[mid] == target:
            return mid
        elif nums[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return left

import random
class Game:
    def __init__(self):
        cards = [1]*7 + [0]*2
        random.shuffle(cards)
        self.cards = cards
        self.revealed = [False]*9
        self.score = 0
        self.zero = 0
        self.moves = 0
        def flip(self, pos):
            if self.moves ==9 or self.zero == 2:
                return self.score
            if self.revealed[pos]:
                return self.score
            self.revealed[pos] = True
            self.moves += 1
            if self.cards[pos] ==1:
                self.sore += 1
            else:
                self.zero += 1
                return self.score
    def over(self):
        return self.moves == 9 or self.zero == 2

def count_ages(path):
    age_count = {}
    with open(path,"r",encoding = "utf-8")as f:
        for line in f:
            for token in line.strip().spit(","):
                if not token.stip():
                    continue
                age = int(token)
                if 0<= age <= 110:
                    age_count[age] = age_count.get(age,0)+1
    return age_count
import csv
