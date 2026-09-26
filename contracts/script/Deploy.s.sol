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
///   PHONE_VERIFIER, PAIR_VERIFIER, MAX_AGE (s, default 900)   noir only: already deployed bb verifiers
///   OWNER_FACTORY / SETUP (optional)  reuse existing ones (a second guard for the Noir switch)
///   DEPLOY_OUT    output json. Default deployments/<chainid>.json. An anvil fork keeps chainid 11155111,
///                 so every anvil run MUST set DEPLOY_OUT=deployments/anvil-11155111.json.
///   PRIVATE_KEY   optional; else use --private-key / --account on the command line
contract Deploy is Script {
    function run() external {
        string memory out = vm.envOr("DEPLOY_OUT", string.concat("deployments/", vm.toString(block.chainid), ".json"));
        string memory kind = vm.envOr("VERIFIER", string("attestation"));
        bool noir = keccak256(bytes(kind)) == keccak256("noir");
        require(noir || keccak256(bytes(kind)) == keccak256("attestation"), "VERIFIER must be attestation|noir");

        uint256 pk = vm.envOr("PRIVATE_KEY", uint256(0));
        if (pk != 0) vm.startBroadcast(pk);
        else vm.startBroadcast();
        IPopPresenceVerifier v = noir
            ? IPopPresenceVerifier(
                new NoirPresenceVerifier(
                    IHonkVerifier(vm.envAddress("PHONE_VERIFIER")),
                    IHonkVerifier(vm.envAddress("PAIR_VERIFIER")),
                    uint64(vm.envOr("MAX_AGE", uint256(900)))
                )
            )
            : IPopPresenceVerifier(new PopAttestationVerifier());
        PopSafeGuard g = new PopSafeGuard(v);
        address s = vm.envOr("SETUP", address(0));
        if (s == address(0)) s = address(new PopSafeSetup());
        address f = vm.envOr("OWNER_FACTORY", address(0));
        if (f == address(0)) f = address(new P256OwnerFactory());
        vm.stopBroadcast();

        string memory o = "deploy";
        vm.serializeUint(o, "chainId", block.chainid);
        vm.serializeUint(o, "block", block.number);
        vm.serializeString(o, "verifierKind", kind);
        vm.serializeAddress(o, "PresenceVerifier", address(v));
        vm.serializeAddress(o, "PopSafeGuard", address(g));
        vm.serializeAddress(o, "PopSafeSetup", s);
        string memory j = vm.serializeAddress(o, "P256OwnerFactory", f);
        vm.writeJson(j, out);
        console.log("wrote", out);
        console.log("PopSafeGuard", address(g));
        console.log("verifier", kind, address(v));
    }
}
