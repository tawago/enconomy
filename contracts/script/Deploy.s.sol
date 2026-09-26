// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import "forge-std/Script.sol";
import {PopSafeGuard, PopSafeSetup} from "../src/PopSafeGuard.sol";
import {P256OwnerFactory} from "../src/P256Owner.sol";
import {PopAttestationVerifier} from "../src/verifiers/PopAttestationVerifier.sol";
import {NoirPresenceVerifier} from "../src/verifiers/NoirPresenceVerifier.sol";
import {IPopPresenceVerifier, IHonkVerifier} from "../src/interfaces/IPopPresenceVerifier.sol";

/// Deploys verifier + PopSafeGuard + PopSafeSetup + P256OwnerFactory (Ethereum Sepolia, chainId 11155111).
/// env:
///   VERIFIER      attestation (default) | noir
///   PHONE_VERIFIER, PAIR_VERIFIER   noir only: already deployed bb verifiers (Sepolia defaults below)
///   MAX_AGE (s)   noir only, default 86400 (24h, demo: no expiry mid-demo)
///   OWNER_FACTORY / SETUP (optional)  reuse existing ones (a second guard for the Noir switch); on Sepolia the
///                 noir path defaults to the live ones in deployments/11155111.json
/// A Safe on the noir guard must pin the server's SBcred3 issuer key (GET /v1/config issuer.pub_x/pub_y), which
/// signs the proofs' issuer inputs and the POPCC1 code_commit attestations. Not the attest-demo key.
///   DEPLOY_OUT    output json. Default deployments/<chainid>.json. An anvil fork keeps chainid 11155111,
///                 so every anvil run MUST set DEPLOY_OUT=deployments/anvil-11155111.json.
///   PRIVATE_KEY   optional; else use --private-key / --account on the command line
contract Deploy is Script {
    // Ethereum Sepolia, already deployed (ZK lane: deployments/zk-sepolia.json on ens/meet-resolver; this lane: 11155111.json)
    address constant SEPOLIA_PHONE_VERIFIER = 0x5b69C5a7D3e5A56D33809b9B95d02984D4aFa791;
    address constant SEPOLIA_PAIR_VERIFIER = 0xfFA0cf3d79E2a27bC11b9E67eDB979a9b5BE3Fd7;
    address constant SEPOLIA_SETUP = 0x3d4e549F13CCee540884481b35Fd1CA42A9E0707;
    address constant SEPOLIA_OWNER_FACTORY = 0x99565991Ec5414Ee2d3A2fA48Ab4d92efBd2466e;

    function run() external {
        string memory out = vm.envOr("DEPLOY_OUT", string.concat("deployments/", vm.toString(block.chainid), ".json"));
        string memory kind = vm.envOr("VERIFIER", string("attestation"));
        bool noir = keccak256(bytes(kind)) == keccak256("noir");
        require(noir || keccak256(bytes(kind)) == keccak256("attestation"), "VERIFIER must be attestation|noir");

        bool sep = block.chainid == 11155111;
        address phoneV = vm.envOr("PHONE_VERIFIER", sep ? SEPOLIA_PHONE_VERIFIER : address(0));
        address pairV = vm.envOr("PAIR_VERIFIER", sep ? SEPOLIA_PAIR_VERIFIER : address(0));
        if (noir) require(phoneV.code.length > 0 && pairV.code.length > 0, "PHONE_VERIFIER/PAIR_VERIFIER not deployed");
        address s = vm.envOr("SETUP", noir && sep ? SEPOLIA_SETUP : address(0));
        address f = vm.envOr("OWNER_FACTORY", noir && sep ? SEPOLIA_OWNER_FACTORY : address(0));

        uint256 pk = vm.envOr("PRIVATE_KEY", uint256(0));
        if (pk != 0) vm.startBroadcast(pk);
        else vm.startBroadcast();
        IPopPresenceVerifier v = noir
            ? IPopPresenceVerifier(
                new NoirPresenceVerifier(
                    IHonkVerifier(phoneV), IHonkVerifier(pairV), uint64(vm.envOr("MAX_AGE", uint256(86_400)))
                )
            )
            : IPopPresenceVerifier(new PopAttestationVerifier());
        PopSafeGuard g = new PopSafeGuard(v);
        if (s == address(0)) s = address(new PopSafeSetup());
        if (f == address(0)) f = address(new P256OwnerFactory());
        vm.stopBroadcast();

        string memory o = "deploy";
        vm.serializeUint(o, "chainId", block.chainid);
        vm.serializeUint(o, "block", block.number);
        vm.serializeString(o, "verifierKind", kind);
        vm.serializeAddress(o, "PresenceVerifier", address(v));
        if (noir) {
            vm.serializeAddress(o, "PhoneVerifier", phoneV);
            vm.serializeAddress(o, "PairVerifier", pairV);
            vm.serializeUint(o, "maxAge", vm.envOr("MAX_AGE", uint256(86_400)));
        }
        vm.serializeAddress(o, "PopSafeGuard", address(g));
        vm.serializeAddress(o, "PopSafeSetup", s);
        string memory j = vm.serializeAddress(o, "P256OwnerFactory", f);
        vm.writeJson(j, out);
        console.log("wrote", out);
        console.log("PopSafeGuard", address(g));
        console.log("verifier", kind, address(v));
    }
}
