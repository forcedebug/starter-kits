import forta_agent
import rlp
from forta_agent import get_json_rpc_url
from joblib import load
from evmdasm import EvmBytecode
from web3 import Web3

from src.constants import (
    BYTE_CODE_LENGTH_THRESHOLD,
    MODEL_THRESHOLD,
    TOKEN_TYPES,
)
from src.findings import MaliciousTokenContractFindings
from src.logger import logger
from src.utils import (
    get_anomaly_score,
    get_features,
    get_storage_addresses,
)


web3 = Web3(Web3.HTTPProvider(get_json_rpc_url()))
ML_MODEL = None


def initialize():
    """
    this function loads the ml model.
    """
    global ML_MODEL
    logger.info("Start loading model")
    ML_MODEL = load("malicious_token_model_sighashes_10_29_22.joblib")
    logger.info("Complete loading model")


def exec_model(w3, opcodes: str) -> tuple:
    """
    this function executes the model to obtain the score for the contract
    :return: score: float
    """
    score = None
    features, opcode_addresses, contract_type = get_features(w3, opcodes)
    if contract_type in TOKEN_TYPES:
        score = ML_MODEL.predict_proba([features])[0][1]
    logger.info(f"{contract_type}: {score}")

    return score, opcode_addresses, contract_type


def detect_malicious_token_contract_tx(
    w3, transaction_event: forta_agent.transaction_event.TransactionEvent
) -> list:
    all_findings = []
    if len(transaction_event.traces) > 0:
        for trace in transaction_event.traces:
            if trace.type == "create":
                created_contract_address = (
                    trace.result.address if trace.result else None
                )
                error = trace.error if trace.error else None
                logger.info(f"Contract created {created_contract_address}")
                if error is not None:
                    nonce = (
                        transaction_event.transaction.nonce
                        if transaction_event.from_ == trace.action.from_
                        else 1
                    )  # for contracts creating other contracts, the nonce would be 1. WARN: this doesn't handle create2 tx
                    contract_address = calc_contract_address(
                        w3, trace.action.from_, nonce
                    )
                    logger.warn(
                        f"Contract {contract_address} creation failed with tx {trace.transactionHash}: {error}"
                    )
                # creation bytecode contains both initialization and run-time bytecode.
                creation_bytecode = trace.action.init
                all_findings.extend(
                    detect_malicious_token_contract(
                        w3,
                        trace.action.from_,
                        created_contract_address,
                        creation_bytecode,
                    )
                )
    else:  # Trace isn't supported, To improve coverage, process contract creations from EOAs.
        if transaction_event.to is None:
            nonce = transaction_event.transaction.nonce
            created_contract_address = calc_contract_address(
                w3, transaction_event.from_, nonce
            )
            runtime_bytecode = w3.eth.get_code(
                Web3.toChecksumAddress(created_contract_address)
            ).hex()
            all_findings.extend(
                detect_malicious_token_contract(
                    w3,
                    transaction_event.from_,
                    created_contract_address,
                    runtime_bytecode,
                )
            )

    return all_findings


def detect_malicious_token_contract(w3, from_, created_contract_address, code) -> list:
    findings = []

    if created_contract_address is not None:
        if len(code) > BYTE_CODE_LENGTH_THRESHOLD:
            try:
                opcodes = EvmBytecode(code).disassemble()
            except Exception as e:
                logger.warn(f"Error disassembling evm bytecode: {e}")
            # obtain all the addresses contained in the created contract and propagate to the findings
            anomaly_score = get_anomaly_score(w3.eth.chain_id)
            storage_addresses = get_storage_addresses(w3, created_contract_address)
            model_score, opcode_addresses, contract_type = exec_model(w3, opcodes)
            if model_score is not None and model_score >= MODEL_THRESHOLD:
                findings.append(
                    MaliciousTokenContractFindings.malicious_contract_creation(
                        from_,
                        contract_type,
                        created_contract_address,
                        set.union(storage_addresses, opcode_addresses),
                        model_score,
                        MODEL_THRESHOLD,
                        anomaly_score,
                    )
                )

    return findings


def calc_contract_address(w3, address, nonce) -> str:
    """
    this function calculates the contract address from sender/nonce
    :return: contract address: str
    """

    address_bytes = bytes.fromhex(address[2:].lower())
    return Web3.toChecksumAddress(Web3.keccak(rlp.encode([address_bytes, nonce]))[-20:])


def provide_handle_transaction(w3):
    def handle_transaction(
        transaction_event: forta_agent.transaction_event.TransactionEvent,
    ) -> list:
        return detect_malicious_token_contract_tx(w3, transaction_event)

    return handle_transaction


real_handle_transaction = provide_handle_transaction(web3)


def handle_transaction(
    transaction_event: forta_agent.transaction_event.TransactionEvent,
):
    return real_handle_transaction(transaction_event)
