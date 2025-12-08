from pathlib import Path
p=Path(r"C:\Users\ekale\Documents\Git\V02\templates\index.html")
s=p.read_text()
pairs={'(':')','{':'}','[':']'}
stack=[]
for i,ch in enumerate(s):
    if ch in pairs:
        stack.append((ch,i))
    elif ch in pairs.values():
        if not stack:
            print('Unmatched closing',ch,'at',i)
            break
        last,idx=stack.pop()
        if pairs[last]!=ch:
            print('Mismatch',last,'->',ch,'at',i)
            break
else:
    if stack:
        print('Unmatched openings:', len(stack), 'top at', stack[-1])
    else:
        print('All braces matched')
