"""
测试交易分类器
"""

from src.types import TxInput, TxCategory
from src.classifier import classify_transaction, is_likely_swap
from src.constants import SELECTOR_TRANSFER, SELECTOR_APPROVE, SELECTOR_SWAP_EXACT_TOKENS


class TestClassifyTransaction:
    def test_permission_op(self):
        tx = TxInput(
            chain_id=1,
            from_address="0x1234",
            to_address="0x5678",
            data=SELECTOR_APPROVE + "0" * 128,  # approve(address,uint256)
        )
        assert classify_transaction(tx) == TxCategory.PERMISSION_OP
    
    def test_asset_op_transfer(self):
        tx = TxInput(
            chain_id=1,
            from_address="0x1234",
            to_address="0x5678",
            data=SELECTOR_TRANSFER + "0" * 128,  # transfer(address,uint256)
        )
        assert classify_transaction(tx) == TxCategory.ASSET_OP
    
    def test_asset_op_eth_transfer(self):
        tx = TxInput(
            chain_id=1,
            from_address="0x1234",
            to_address="0x5678",
            data="0x",
            value=1000,
        )
        assert classify_transaction(tx) == TxCategory.ASSET_OP
    
    def test_non_asset_op(self):
        tx = TxInput(
            chain_id=1,
            from_address="0x1234",
            to_address="0x5678",
            data="0x12345678" + "0" * 64,  # 未知函数
        )
        assert classify_transaction(tx) == TxCategory.NON_ASSET_OP
    
    def test_contract_creation(self):
        tx = TxInput(
            chain_id=1,
            from_address="0x1234",
            to_address=None,  # 合约创建
            data="0x608060405234801561001057600080fd5b50",
        )
        assert classify_transaction(tx) == TxCategory.NON_ASSET_OP


class TestIsLikelySwap:
    def test_swap_function(self):
        tx = TxInput(
            chain_id=1,
            from_address="0x1234",
            to_address="0x5678",
            data=SELECTOR_SWAP_EXACT_TOKENS + "0" * 128,
        )
        assert is_likely_swap(tx)
    
    def test_non_swap(self):
        tx = TxInput(
            chain_id=1,
            from_address="0x1234",
            to_address="0x5678",
            data=SELECTOR_TRANSFER + "0" * 128,
        )
        assert not is_likely_swap(tx)
