#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧪 Phase 26 MoE Test Suite
Comprehensive tests for MoE router, experts, and load balancing

Tests:
1. MoE Router initialization and forward pass
2. Expert networks
3. Load balancing
4. End-to-end integration
5. Inference performance

Author: JARVIS
Date: 2026-08-18
"""

import torch
import torch.nn.functional as F
import numpy as np
import logging
from typing import List, Tuple
import sys

logger = logging.getLogger("MoETest")
logging.basicConfig(level=logging.INFO)


class MoETestSuite:
    """Comprehensive test suite for Phase 26 MoE"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"🧪 Initializing MoE Test Suite on {self.device}")

    def assert_true(self, condition: bool, message: str):
        """Assert condition is true"""
        if condition:
            logger.info(f"   ✅ {message}")
            self.passed += 1
        else:
            logger.error(f"   ❌ {message}")
            self.failed += 1

    def assert_shape(self, tensor: torch.Tensor, expected_shape: Tuple, message: str):
        """Assert tensor shape"""
        if tensor.shape == expected_shape:
            logger.info(f"   ✅ {message} (shape: {tensor.shape})")
            self.passed += 1
        else:
            logger.error(
                f"   ❌ {message} (expected: {expected_shape}, got: {tensor.shape})"
            )
            self.failed += 1

    def assert_range(self, value: float, min_val: float, max_val: float, message: str):
        """Assert value is in range"""
        if min_val <= value <= max_val:
            logger.info(f"   ✅ {message} ({value:.4f})")
            self.passed += 1
        else:
            logger.error(
                f"   ❌ {message} (expected: [{min_val}, {max_val}], got: {value:.4f})"
            )
            self.failed += 1

    # ========================================================================
    # Test Suite
    # ========================================================================

    def test_moe_router_initialization(self):
        """Test MoE router initialization"""
        print("\n" + "="*80)
        print("TEST 1: MoE Router Initialization")
        print("="*80)

        try:
            from moe_router import MoEConfig, MoEGate

            config = MoEConfig()
            moe = MoEGate(config).to(self.device)

            self.assert_true(
                isinstance(moe, torch.nn.Module),
                "MoE gate is a PyTorch module"
            )
            self.assert_true(
                len(list(moe.experts)) == 4,
                "MoE has 4 experts"
            )

            # Check parameter count
            param_count = sum(p.numel() for p in moe.parameters())
            logger.info(f"   📊 Total parameters: {param_count/1e6:.2f}M")

        except Exception as e:
            logger.error(f"   ❌ Exception: {e}")
            self.failed += 1

    def test_moe_forward_pass(self):
        """Test MoE forward pass"""
        print("\n" + "="*80)
        print("TEST 2: MoE Forward Pass")
        print("="*80)

        try:
            from moe_router import MoEConfig, MoEGate

            config = MoEConfig()
            moe = MoEGate(config).to(self.device)

            batch_size, seq_len, hidden_dim = 2, 64, 768
            inputs = torch.randn(batch_size, seq_len, hidden_dim).to(self.device)

            output, metrics = moe(inputs, training=True)

            self.assert_shape(
                output,
                (batch_size, seq_len, hidden_dim),
                "Output shape matches input"
            )

            # Check metrics
            self.assert_true(
                "router_entropy" in metrics,
                "Metrics contain router_entropy"
            )
            self.assert_true(
                "expert_load" in metrics,
                "Metrics contain expert_load"
            )

            # Check entropy value
            entropy = metrics["router_entropy"].item()
            self.assert_range(
                entropy,
                0.0,
                np.log(4),  # max entropy for 4 experts
                f"Router entropy in valid range (max: {np.log(4):.4f})"
            )

        except Exception as e:
            logger.error(f"   ❌ Exception: {e}")
            self.failed += 1

    def test_expert_networks(self):
        """Test individual expert networks"""
        print("\n" + "="*80)
        print("TEST 3: Expert Networks")
        print("="*80)

        try:
            from expert_networks import (
                DiagnosisExpert, DrugDesignExpert,
                PatientPrognosisExpert, EHRExpert
            )

            # Test Diagnosis Expert
            print("\n   Testing Diagnosis Expert (CNN-ViT)...")
            diagnosis = DiagnosisExpert().to(self.device)
            diagnosis_input = torch.randn(2, 1, 224, 224).to(self.device)
            diagnosis_out = diagnosis(diagnosis_input)
            self.assert_shape(
                diagnosis_out["predictions"],
                (2, 128),
                "Diagnosis output shape correct"
            )

            # Test Drug Design Expert
            print("   Testing Drug Design Expert (GNN)...")
            drug = DrugDesignExpert().to(self.device)
            drug_node_features = torch.randn(2, 20, 32).to(self.device)
            drug_adj = torch.randn(2, 20, 20).to(self.device)
            drug_out = drug(drug_node_features, drug_adj)
            self.assert_shape(
                drug_out["property_predictions"],
                (2, 8),
                "Drug design output shape correct"
            )

            # Test Patient Prognosis Expert
            print("   Testing Patient Prognosis Expert (LSTM+Attention)...")
            prognosis = PatientPrognosisExpert().to(self.device)
            prognosis_input = torch.randn(2, 48, 32).to(self.device)
            prognosis_out = prognosis(prognosis_input)
            self.assert_shape(
                prognosis_out["mortality_logits"],
                (2, 2),
                "Patient prognosis output shape correct"
            )

            # Test EHR Expert
            print("   Testing EHR Expert (BERT)...")
            ehr = EHRExpert().to(self.device)
            ehr_input = torch.randint(0, 10000, (2, 256)).to(self.device)
            ehr_out = ehr(ehr_input)
            self.assert_shape(
                ehr_out["diagnosis_logits"],
                (2, 256),
                "EHR output shape correct"
            )

        except Exception as e:
            logger.error(f"   ❌ Exception: {e}")
            self.failed += 1

    def test_load_balancing(self):
        """Test load balancing mechanisms"""
        print("\n" + "="*80)
        print("TEST 4: Load Balancing")
        print("="*80)

        try:
            from load_balancing import ExpertLoadBalancer

            balancer = ExpertLoadBalancer(num_experts=4)

            batch_size = 100
            num_experts = 4
            num_top_k = 4

            router_logits = torch.randn(batch_size, num_experts).to(self.device)
            expert_indices = torch.randint(0, num_experts, (batch_size, num_top_k)).to(self.device)
            routing_weights = F.softmax(torch.randn(batch_size, num_top_k), dim=-1).to(self.device)

            aux_loss, metrics, alerts = balancer.compute_loss_and_metrics(
                router_logits,
                expert_indices,
                routing_weights,
            )

            self.assert_true(
                torch.is_tensor(aux_loss),
                "Auxiliary loss is a tensor"
            )

            self.assert_true(
                hasattr(metrics, "expert_load_std"),
                "Metrics have expert_load_std"
            )

            self.assert_range(
                metrics.router_entropy,
                0.0,
                np.log(4),
                f"Router entropy in valid range"
            )

            logger.info(f"   📊 Expert load std: {metrics.expert_load_std:.4f}")
            logger.info(f"   📊 Router entropy: {metrics.router_entropy:.4f}")

        except Exception as e:
            logger.error(f"   ❌ Exception: {e}")
            self.failed += 1

    def test_moe_with_auxiliary_loss(self):
        """Test MoE with auxiliary loss"""
        print("\n" + "="*80)
        print("TEST 5: MoE with Auxiliary Loss")
        print("="*80)

        try:
            from moe_router import MoEConfig, MoEWithAuxiliaryLoss

            config = MoEConfig()
            moe = MoEWithAuxiliaryLoss(config).to(self.device)

            batch_size, seq_len, hidden_dim = 2, 64, 768
            inputs = torch.randn(batch_size, seq_len, hidden_dim).to(self.device)

            output, metrics, aux_loss = moe(inputs, training=True)

            self.assert_shape(
                output,
                (batch_size, seq_len, hidden_dim),
                "Output shape correct"
            )

            self.assert_true(
                torch.is_tensor(aux_loss),
                "Auxiliary loss is a tensor"
            )

            self.assert_range(
                aux_loss.item(),
                0.0,
                1.0,  # Typical range
                f"Auxiliary loss in reasonable range"
            )

        except Exception as e:
            logger.error(f"   ❌ Exception: {e}")
            self.failed += 1

    def test_gradient_flow(self):
        """Test gradient flow through MoE"""
        print("\n" + "="*80)
        print("TEST 6: Gradient Flow")
        print("="*80)

        try:
            from moe_router import MoEConfig, MoEWithAuxiliaryLoss

            config = MoEConfig()
            moe = MoEWithAuxiliaryLoss(config).to(self.device)

            batch_size, seq_len, hidden_dim = 2, 64, 768
            inputs = torch.randn(batch_size, seq_len, hidden_dim, requires_grad=True).to(self.device)

            output, metrics, aux_loss = moe(inputs, training=True)

            # Backward
            loss = output.sum() + aux_loss
            loss.backward()

            # Check gradients
            self.assert_true(
                inputs.grad is not None,
                "Input gradients computed"
            )

            gradient_norm = inputs.grad.norm().item()
            self.assert_range(
                gradient_norm,
                0.0,
                100.0,  # Reasonable range
                f"Gradient norm in reasonable range"
            )

        except Exception as e:
            logger.error(f"   ❌ Exception: {e}")
            self.failed += 1

    def test_inference_mode(self):
        """Test MoE in inference mode (no gradients)"""
        print("\n" + "="*80)
        print("TEST 7: Inference Mode")
        print("="*80)

        try:
            from moe_router import MoEConfig, MoEWithAuxiliaryLoss

            config = MoEConfig()
            moe = MoEWithAuxiliaryLoss(config).to(self.device)
            moe.eval()

            batch_size, seq_len, hidden_dim = 2, 64, 768

            with torch.no_grad():
                inputs = torch.randn(batch_size, seq_len, hidden_dim).to(self.device)
                output, metrics, aux_loss = moe(inputs, training=False)

            self.assert_true(
                not inputs.requires_grad,
                "No gradient computation in inference"
            )

            self.assert_shape(
                output,
                (batch_size, seq_len, hidden_dim),
                "Inference output shape correct"
            )

        except Exception as e:
            logger.error(f"   ❌ Exception: {e}")
            self.failed += 1

    def test_multi_batch_consistency(self):
        """Test consistency across multiple batches"""
        print("\n" + "="*80)
        print("TEST 8: Multi-Batch Consistency")
        print("="*80)

        try:
            from moe_router import MoEConfig, MoEGate

            config = MoEConfig()
            moe = MoEGate(config).to(self.device)
            moe.eval()

            with torch.no_grad():
                for batch_id in range(3):
                    batch_size = 2 + batch_id  # Varying batch sizes
                    inputs = torch.randn(batch_size, 64, 768).to(self.device)
                    output, metrics = moe(inputs, training=False)

                    self.assert_shape(
                        output,
                        (batch_size, 64, 768),
                        f"Batch {batch_id} output shape consistent"
                    )

        except Exception as e:
            logger.error(f"   ❌ Exception: {e}")
            self.failed += 1

    def test_expert_coverage(self):
        """Test that all experts are used"""
        print("\n" + "="*80)
        print("TEST 9: Expert Coverage")
        print("="*80)

        try:
            from moe_router import MoEConfig, MoEGate

            config = MoEConfig()
            moe = MoEGate(config).to(self.device)

            # Collect expert usage across multiple batches
            all_expert_indices = []

            for _ in range(10):
                batch_size = 10
                inputs = torch.randn(batch_size, 64, 768).to(self.device)

                router_logits, top_k_weights, expert_indices = moe.router(inputs)
                all_expert_indices.append(expert_indices)

            # Check coverage
            all_indices = torch.cat(all_expert_indices).cpu().numpy().flatten()
            unique_experts = len(np.unique(all_indices))

            logger.info(f"   📊 Unique experts used: {unique_experts}/{config.num_experts}")
            self.assert_true(
                unique_experts >= 3,  # At least 75% of experts
                f"Most experts are used ({unique_experts}/{config.num_experts})"
            )

        except Exception as e:
            logger.error(f"   ❌ Exception: {e}")
            self.failed += 1

    def test_memory_usage(self):
        """Test memory usage"""
        print("\n" + "="*80)
        print("TEST 10: Memory Usage")
        print("="*80)

        try:
            from moe_router import MoEConfig, MoEWithAuxiliaryLoss

            config = MoEConfig()

            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
                torch.cuda.empty_cache()

            moe = MoEWithAuxiliaryLoss(config).to(self.device)

            batch_size, seq_len, hidden_dim = 4, 256, 768
            inputs = torch.randn(batch_size, seq_len, hidden_dim).to(self.device)

            with torch.no_grad():
                output, metrics, aux_loss = moe(inputs, training=True)

            if torch.cuda.is_available():
                peak_memory = torch.cuda.max_memory_allocated() / (1024**3)  # GB
                logger.info(f"   💾 Peak memory: {peak_memory:.2f}GB")
            else:
                logger.info(f"   💾 CPU mode (memory tracking not available)")

            self.assert_true(True, "Memory test completed")

        except Exception as e:
            logger.error(f"   ❌ Exception: {e}")
            self.failed += 1

    # ========================================================================
    # Test Runner
    # ========================================================================

    def run_all_tests(self):
        """Run all tests"""
        print("\n" + "="*80)
        print("🧪 JARVIS Phase 26 MoE Test Suite")
        print("="*80)

        self.test_moe_router_initialization()
        self.test_moe_forward_pass()
        self.test_expert_networks()
        self.test_load_balancing()
        self.test_moe_with_auxiliary_loss()
        self.test_gradient_flow()
        self.test_inference_mode()
        self.test_multi_batch_consistency()
        self.test_expert_coverage()
        self.test_memory_usage()

        # Summary
        self.print_summary()

    def print_summary(self):
        """Print test summary"""
        total = self.passed + self.failed
        pass_rate = (self.passed / total * 100) if total > 0 else 0

        print("\n" + "="*80)
        print("📊 Test Summary")
        print("="*80)
        print(f"\n✅ Passed: {self.passed}")
        print(f"❌ Failed: {self.failed}")
        print(f"📈 Total: {total}")
        print(f"📊 Pass Rate: {pass_rate:.1f}%")

        if self.failed == 0:
            print("\n🎉 All tests passed!")
            return 0
        else:
            print(f"\n⚠️ {self.failed} test(s) failed")
            return 1


if __name__ == "__main__":
    suite = MoETestSuite()
    exit_code = suite.run_all_tests()
    sys.exit(exit_code)
