pragma circom 2.1.8;

// Presence-gated shielded transfer (no ASP). One input note -> change note + payee note.
// Nothing about amount, payer or payee is public.
//
// payerTag       = Poseidon(TAG_PAYER, existingNullifier)
// payeeCommitment= Poseidon(transferValue, 0, payeePrecommitment)   (0xbow note format, label 0)
// presenceLeaf   = Poseidon(TAG_PRES, payerTag, payeeCommitment)    (posted by the PoP attester)

include "./commitment.circom";
include "./merkleTree.circom";

template PresenceTransfer(maxTreeDepth, presDepth) {
  // public
  signal input stateRoot;
  signal input stateTreeDepth;
  signal input presenceRoot;
  signal input presenceTreeDepth;
  signal input context;             // keccak(Transfer struct, SCOPE) % p, binds relayer/fee data

  // private
  signal input label;
  signal input existingValue;
  signal input existingNullifier;
  signal input existingSecret;
  signal input newNullifier;
  signal input newSecret;
  signal input transferValue;
  signal input payeePrecommitment;
  signal input stateSiblings[maxTreeDepth];
  signal input stateIndex;
  signal input presenceSiblings[presDepth];
  signal input presenceIndex;

  signal output existingNullifierHash;
  signal output changeCommitment;
  signal output payeeCommitment;

  // 1. input note
  component inC = CommitmentHasher();
  inC.value <== existingValue;
  inC.label <== label;
  inC.nullifier <== existingNullifier;
  inC.secret <== existingSecret;
  existingNullifierHash <== inC.nullifierHash;

  component st = LeanIMTInclusionProof(maxTreeDepth);
  st.leaf <== inC.commitment;
  st.leafIndex <== stateIndex;
  st.siblings <== stateSiblings;
  st.actualDepth <== stateTreeDepth;
  stateRoot === st.out;

  // 2. value conservation, 128-bit ranges
  signal remaining <== existingValue - transferValue;
  component r1 = Num2Bits(128); r1.in <== remaining;
  component r2 = Num2Bits(128); r2.in <== transferValue;

  // 3. change note (keeps the payer's label)
  component ne = IsEqual();
  ne.in[0] <== existingNullifier;
  ne.in[1] <== newNullifier;
  ne.out === 0;
  component chC = CommitmentHasher();
  chC.value <== remaining;
  chC.label <== label;
  chC.nullifier <== newNullifier;
  chC.secret <== newSecret;
  changeCommitment <== chC.commitment;

  // 4. payee note, label 0
  component pc = Poseidon(3);
  pc.inputs[0] <== transferValue;
  pc.inputs[1] <== 0x706f702d7472616e73666572;
  pc.inputs[2] <== payeePrecommitment;
  payeeCommitment <== pc.out;

  // 5. presence ticket
  var TAG_PAYER = 0x706f702d7061796572;   // "pop-payer"
  var TAG_PRES  = 0x706f702d70726573;     // "pop-pres"
  component pt = Poseidon(2);
  pt.inputs[0] <== TAG_PAYER;
  pt.inputs[1] <== existingNullifier;
  component lf = Poseidon(3);
  lf.inputs[0] <== TAG_PRES;
  lf.inputs[1] <== pt.out;
  lf.inputs[2] <== payeeCommitment;
  component pr = LeanIMTInclusionProof(presDepth);
  pr.leaf <== lf.out;
  pr.leafIndex <== presenceIndex;
  pr.siblings <== presenceSiblings;
  pr.actualDepth <== presenceTreeDepth;
  presenceRoot === pr.out;

  signal contextSquared <== context * context;
}

component main {public [stateRoot, stateTreeDepth, presenceRoot, presenceTreeDepth, context]} = PresenceTransfer(32, 20);
