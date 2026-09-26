# Observer model for presence-pool (0xbow fork). Public: Deposited(depositor,value,t), Transferred(t) (amount hidden),
# Withdrawn(value,recipient,t). Observer asks: which deposit funded the demo transfer? which withdraw is the payee?
# Candidate funder = any deposit note unspent at transfer time with value >= min plausible pay (unknown -> any).
# Candidate payee withdraw = withdraws after the transfer whose value could come from the payee note:
#   observer can't tell a payee-note withdraw from a deposit-note withdraw unless value > every other unspent note.
def run(name, deposits, transfer_t, withdraws, pay):
    # deposits: list of (who, value, t); withdraws: list of (who, value, t)
    funders = [d for d in deposits if d[2] < transfer_t and d[1] >= pay]
    naive_last = max((d for d in deposits if d[2] < transfer_t), key=lambda d: d[2])
    # payee withdraw candidates: withdraws after transfer with the same value as the real payee withdraw
    real = [w for w in withdraws if w[0]=="Q"]
    same = [w for w in withdraws if real and w[1]==real[0][1] and w[2]>transfer_t]
    print(f"{name}: funder set={len(funders)} (last-deposit heuristic picks {naive_last[0]}), "
          f"payee-withdraw set={len(same) if real else 'n/a'}")
D=0.001
run("A fresh pool, 1 deposit", [("P",D,0)], 10, [("Q",0.0003,20)], 0.0003)
run("B fresh pool, odd amount", [("P",0.0137,0),("x",0.001,1)], 10, [("Q",0.0137,20)], 0.0137)
dec=[(f"d{i}",D,i) for i in range(12)]
run("C 12 decoys, P deposits LAST", dec+[("P",D,50)], 60, [("Q",0.0003,70)], 0.0003)
run("D 12 decoys, P interleaved, pay menu, decoy withdraws same menu",
    dec[:6]+[("P",D,6.5)]+dec[6:], 60,
    [(f"d{i}",v,61+i) for i,v in enumerate([0.0003,0.0005,0.0003,0.001,0.0003,0.0002])]+[("Q",0.0003,80)], 0.0003)
run("E same as D but pay = whole note 0.001",
    dec[:6]+[("P",D,6.5)]+dec[6:], 60,
    [(f"d{i}",D,61+i) for i in range(6)]+[("Q",D,80)], D)
