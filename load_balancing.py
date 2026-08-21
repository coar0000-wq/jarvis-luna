#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
⚖️ Phase 26 Load Balancing & Monitoring
Prevent Expert Collapse and ensure balanced expert utilization

Mechanisms:
1. Auxiliary Loss: Router entropy regulation
2. Expert Dropout: 5% dropout for regularization
3. Load Monitoring: Daily monitoring with alerts
4. Metrics: Load std < 10%, Router entropy > 0.95

Author: JARVIS
Date: 2026-08-18
Timeline: 2027-01~06 Monitoring Phase
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from collections import deque
import numpy as np
import logging
from datetime import datetime

logger = logging.getLogger("LoadBalancing")


@dataclass
class LoadBalancingMetrics:
    """Load balancing metrics tracker"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    num_tokens: int = 0
    num_experts: int = 4

    # Per-expert metrics
    expert_load: List[float] = field(default_factory=list)
    expert_load_mean: float = 0.0
    expert_load_std: float = 0.0
    expert_load_min: float = 0.0
    expert_load_max: float = 0.0

    # Routing metrics
    router_entropy: float = 0.0
    routing_confidence: float = 0.0
    sparsity: float = 0.0

    # Loss metrics
    auxiliary_loss: float = 0.0
    load_loss: float = 0.0
    entropy_loss: float = 0.0

    def __str__(self) -> str:
        return (
            f"⚖️ Load Balancing Metrics ({self.timestamp})\n"
            f"   Expert Load: mean={self.expert_load_mean:.3f}, "
            f"std={self.expert_load_std:.3f} (target: <0.10)\n"
            f"   Expert Distribution: min={self.expert_load_min:.3f}, "
            f"max={self.expert_load_max:.3f}\n"
            f"   Router Entropy: {self.router_entropy:.4f} (target: >0.95)\n"
            f"   Routing Confidence: {self.routing_confidence:.4f}\n"
            f"   Sparsity: {self.sparsity:.1%}\n"
            f"   Auxiliary Loss: {self.auxiliary_loss:.6f}"
        )


class LoadBalancingMonitor:
    """
    Real-time load balancing monitor
    Tracks expert utilization and detects imbalances
    """

    def __init__(
        self,
        num_experts: int = 4,
        history_window: int = 100,
        load_std_threshold: float = 0.10,
        entropy_threshold: float = 0.95,
    ):
        self.num_experts = num_experts
        self.history_window = history_window
        self.load_std_threshold = load_std_threshold
        self.entropy_threshold = entropy_threshold

        # Metrics history
        self.metrics_history = deque(maxlen=history_window)
        self.load_history = deque(maxlen=history_window)

        logger.info(
            f"🔍 LoadBalancingMonitor initialized\n"
            f"   • Num experts: {num_experts}\n"
            f"   • History window: {history_window}\n"
            f"   • Load std threshold: {load_std_threshold}\n"
            f"   • Entropy threshold: {entropy_threshold}"
        )

    def compute_metrics(
        self,
        expert_indices: torch.Tensor,
        router_logits: torch.Tensor,
        routing_weights: torch.Tensor,
    ) -> LoadBalancingMetrics:
        """
        Compute load balancing metrics

        Args:
            expert_indices: (batch*seq_len, num_top_k) - Selected expert indices
            router_logits: (batch*seq_len, num_experts) - Router logits
            routing_weights: (batch*seq_len, num_top_k) - Top-k routing weights

        Returns:
            metrics: LoadBalancingMetrics instance
        """
        num_tokens = expert_indices.shape[0]

        # 1. Compute expert load (percentage of tokens)
        expert_load = torch.zeros(self.num_experts, device=expert_indices.device)
        for expert_id in range(self.num_experts):
            count = (expert_indices == expert_id).sum().float()
            expert_load[expert_id] = count / num_tokens

        expert_load_np = expert_load.cpu().numpy()

        # 2. Router entropy (measure of routing diversity)
        router_probs = F.softmax(router_logits, dim=-1)
        entropy = -(router_probs * torch.log(router_probs + 1e-9)).sum(dim=-1).mean()

        # 3. Routing confidence (max probability in top-k)
        routing_confidence = routing_weights.max(dim=-1)[0].mean()

        # 4. Sparsity (fraction of active experts)
        active_experts = (expert_load > 0).sum().float()
        sparsity = active_experts / self.num_experts

        # Create metrics object
        metrics = LoadBalancingMetrics(
            num_tokens=num_tokens,
            num_experts=self.num_experts,
            expert_load=expert_load_np.tolist(),
            expert_load_mean=expert_load_np.mean(),
            expert_load_std=expert_load_np.std(),
            expert_load_min=expert_load_np.min(),
            expert_load_max=expert_load_np.max(),
            router_entropy=entropy.item(),
            routing_confidence=routing_confidence.item(),
            sparsity=sparsity.item(),
        )

        return metrics

    def check_load_balance(self, metrics: LoadBalancingMetrics) -> Dict[str, bool]:
        """
        Check if metrics meet target thresholds

        Returns:
            alerts: Dict with 'load_balanced', 'entropy_ok', 'sparsity_ok'
        """
        load_balanced = metrics.expert_load_std < self.load_std_threshold
        entropy_ok = metrics.router_entropy > self.entropy_threshold
        sparsity_ok = metrics.sparsity >= 0.75  # At least 75% of experts active

        alerts = {
            "load_balanced": load_balanced,
            "entropy_ok": entropy_ok,
            "sparsity_ok": sparsity_ok,
            "all_ok": load_balanced and entropy_ok and sparsity_ok,
        }

        return alerts

    def log_metrics(self, metrics: LoadBalancingMetrics, step: int = None):
        """Log metrics to history and console"""
        self.metrics_history.append(metrics)

        # Console output
        status = "✅" if len(self.metrics_history) > 0 else "⚠️"
        logger.info(f"{status} {metrics}")

        # Check for alerts
        alerts = self.check_load_balance(metrics)
        if not alerts["load_balanced"]:
            logger.warning(
                f"⚠️ Expert Load Imbalance Detected!\n"
                f"   Std: {metrics.expert_load_std:.3f} (threshold: {self.load_std_threshold})\n"
                f"   Distribution: {metrics.expert_load}"
            )
        if not alerts["entropy_ok"]:
            logger.warning(
                f"⚠️ Low Router Entropy!\n"
                f"   Entropy: {metrics.router_entropy:.4f} (target: {self.entropy_threshold})"
            )

    def get_summary_stats(self) -> Dict[str, float]:
        """Get summary statistics over recent history"""
        if not self.metrics_history:
            return {}

        metrics_list = list(self.metrics_history)
        load_stds = [m.expert_load_std for m in metrics_list]
        entropies = [m.router_entropy for m in metrics_list]
        sparsities = [m.sparsity for m in metrics_list]

        return {
            "mean_load_std": np.mean(load_stds),
            "min_load_std": np.min(load_stds),
            "max_load_std": np.max(load_stds),
            "mean_entropy": np.mean(entropies),
            "min_entropy": np.min(entropies),
            "mean_sparsity": np.mean(sparsities),
            "num_samples": len(metrics_list),
        }


class AuxiliaryLossComputer(nn.Module):
    """
    Compute auxiliary loss for load balancing
    Prevents expert collapse and encourages balanced routing
    """

    def __init__(
        self,
        num_experts: int = 4,
        loss_weight: float = 0.01,
    ):
        super().__init__()
        self.num_experts = num_experts
        self.loss_weight = loss_weight

        logger.info(
            f"🎯 AuxiliaryLossComputer initialized\n"
            f"   • Num experts: {num_experts}\n"
            f"   • Loss weight: {loss_weight}"
        )

    def forward(
        self,
        router_logits: torch.Tensor,
        expert_indices: torch.Tensor,
    ) -> Tuple[torch.Tensor, Dict[str, torch.Tensor]]:
        """
        Compute auxiliary loss

        Args:
            router_logits: (batch*seq_len, num_experts)
            expert_indices: (batch*seq_len, num_top_k)

        Returns:
            auxiliary_loss: Scalar loss
            loss_components: Dict with individual loss terms
        """
        batch_tokens = router_logits.shape[0]

        # 1. Expert Load Balance Loss
        # Target: each expert should process ~1/num_experts of tokens
        expert_load = torch.zeros(self.num_experts, device=router_logits.device)
        for expert_id in range(self.num_experts):
            count = (expert_indices == expert_id).sum().float()
            expert_load[expert_id] = count / batch_tokens

        target_load = 1.0 / self.num_experts
        load_loss = ((expert_load - target_load) ** 2).sum()

        # 2. Router Entropy Loss
        # Target: maximize entropy (uniform distribution over experts)
        router_probs = F.softmax(router_logits, dim=-1)
        entropy = -(router_probs * torch.log(router_probs + 1e-9)).sum(dim=-1).mean()

        # Entropy should be high (near log(num_experts))
        max_entropy = np.log(self.num_experts)
        target_entropy = max_entropy * 0.90  # 90% of maximum
        entropy_loss = F.relu(target_entropy - entropy)

        # 3. Combined auxiliary loss
        auxiliary_loss = (
            load_loss +
            0.1 * entropy_loss  # Weight entropy loss less
        ) * self.loss_weight

        loss_components = {
            "load_loss": load_loss,
            "entropy_loss": entropy_loss,
            "auxiliary_loss": auxiliary_loss,
            "entropy": entropy,
            "target_entropy": torch.tensor(target_entropy),
        }

        return auxiliary_loss, loss_components


class ExpertLoadBalancer:
    """
    High-level expert load balancer
    Combines monitoring and loss computation
    """

    def __init__(
        self,
        num_experts: int = 4,
        load_std_threshold: float = 0.10,
        entropy_threshold: float = 0.95,
        loss_weight: float = 0.01,
    ):
        self.monitor = LoadBalancingMonitor(
            num_experts=num_experts,
            load_std_threshold=load_std_threshold,
            entropy_threshold=entropy_threshold,
        )

        self.auxiliary_loss_computer = AuxiliaryLossComputer(
            num_experts=num_experts,
            loss_weight=loss_weight,
        )

        logger.info("✅ ExpertLoadBalancer initialized")

    def compute_loss_and_metrics(
        self,
        router_logits: torch.Tensor,
        expert_indices: torch.Tensor,
        routing_weights: torch.Tensor,
    ) -> Tuple[torch.Tensor, LoadBalancingMetrics, Dict[str, bool]]:
        """
        Compute auxiliary loss and load balancing metrics

        Args:
            router_logits: (batch*seq_len, num_experts)
            expert_indices: (batch*seq_len, num_top_k)
            routing_weights: (batch*seq_len, num_top_k)

        Returns:
            auxiliary_loss: Scalar loss
            metrics: LoadBalancingMetrics
            alerts: Dict with alert flags
        """
        # Compute auxiliary loss
        auxiliary_loss, loss_components = self.auxiliary_loss_computer(
            router_logits,
            expert_indices,
        )

        # Compute metrics
        metrics = self.monitor.compute_metrics(
            expert_indices,
            router_logits,
            routing_weights,
        )

        # Add loss components to metrics
        metrics.auxiliary_loss = auxiliary_loss.item()
        metrics.load_loss = loss_components["load_loss"].item()
        metrics.entropy_loss = loss_components["entropy_loss"].item()

        # Check for alerts
        alerts = self.monitor.check_load_balance(metrics)

        return auxiliary_loss, metrics, alerts

    def log_and_return(
        self,
        auxiliary_loss: torch.Tensor,
        metrics: LoadBalancingMetrics,
        alerts: Dict[str, bool],
        step: int = None,
    ) -> Dict:
        """Log metrics and return summary"""
        self.monitor.log_metrics(metrics, step)

        summary = {
            "auxiliary_loss": auxiliary_loss.item() if torch.is_tensor(auxiliary_loss) else auxiliary_loss,
            "metrics": metrics,
            "alerts": alerts,
            "summary_stats": self.monitor.get_summary_stats(),
        }

        return summary


# ============================================================================
# Monitoring Utilities
# ============================================================================

def print_load_balance_report(metrics: LoadBalancingMetrics):
    """Print detailed load balance report"""
    print("\n" + "="*80)
    print(f"📊 Load Balance Report ({metrics.timestamp})")
    print("="*80)

    print(f"\n🔍 Expert Load Distribution:")
    for i, load in enumerate(metrics.expert_load):
        target = 1.0 / metrics.num_experts
        diff = load - target
        bar = "█" * int(load * 50)
        print(f"   Expert {i}: {load:6.2%} {bar} (target: {target:.2%}, diff: {diff:+.2%})")

    print(f"\n📈 Load Statistics:")
    print(f"   Mean: {metrics.expert_load_mean:.2%}")
    print(f"   Std:  {metrics.expert_load_std:.4f} (target: <0.10)")
    print(f"   Min:  {metrics.expert_load_min:.2%}")
    print(f"   Max:  {metrics.expert_load_max:.2%}")

    print(f"\n🎯 Routing Metrics:")
    print(f"   Router Entropy: {metrics.router_entropy:.4f} (target: >0.95)")
    print(f"   Routing Confidence: {metrics.routing_confidence:.4f}")
    print(f"   Sparsity: {metrics.sparsity:.1%}")

    print(f"\n💊 Loss Metrics:")
    print(f"   Auxiliary Loss: {metrics.auxiliary_loss:.6f}")
    print(f"   Load Loss: {metrics.load_loss:.6f}")
    print(f"   Entropy Loss: {metrics.entropy_loss:.6f}")

    print("="*80 + "\n")


if __name__ == "__main__":
    print("\n" + "="*80)
    print("⚖️ Testing Load Balancing")
    print("="*80)

    # Create load balancer
    balancer = ExpertLoadBalancer(
        num_experts=4,
        load_std_threshold=0.10,
        entropy_threshold=0.95,
    )

    # Simulate routing
    batch_size = 100
    num_experts = 4
    num_top_k = 4

    router_logits = torch.randn(batch_size, num_experts)
    expert_indices = torch.randint(0, num_experts, (batch_size, num_top_k))
    routing_weights = F.softmax(torch.randn(batch_size, num_top_k), dim=-1)

    print("\n🧪 Computing loss and metrics...")
    aux_loss, metrics, alerts = balancer.compute_loss_and_metrics(
        router_logits,
        expert_indices,
        routing_weights,
    )

    print(f"\n✅ Auxiliary Loss: {aux_loss.item():.6f}")
    print(f"✅ Alerts: {alerts}")

    # Print detailed report
    print_load_balance_report(metrics)

    # Test multiple iterations
    print("\n📊 Testing over 10 iterations...")
    for i in range(10):
        router_logits = torch.randn(batch_size, num_experts)
        expert_indices = torch.randint(0, num_experts, (batch_size, num_top_k))
        routing_weights = F.softmax(torch.randn(batch_size, num_top_k), dim=-1)

        aux_loss, metrics, alerts = balancer.compute_loss_and_metrics(
            router_logits,
            expert_indices,
            routing_weights,
        )
        balancer.monitor.log_metrics(metrics)

    # Summary statistics
    summary = balancer.monitor.get_summary_stats()
    print("\n📈 Summary Statistics (over 10 iterations):")
    for key, value in summary.items():
        print(f"   {key}: {value:.4f}")

    print("\n✅ Load Balancing tests completed!")
    print("="*80 + "\n")
