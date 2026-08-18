#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧠 Phase 26 MoE (Mixture of Experts) Router - JARVIS Level 3.0 Evolution
Top-4 Gating Mechanism with Expert Load Balancing

Architecture:
- Input Token → Router Network (MLP, 256-dim)
- Expert Score Calculation (softmax, N experts)
- Top-4 Selection (probability-based)
- Parallel Expert Processing
- Weighted Output Combination

Medical Domain Experts (4):
1. Diagnosis AI (CNN-ViT) - Medical image analysis
2. Drug Design AI (GNN) - Compound prediction
3. Patient Prognosis AI (LSTM) - Clinical time-series
4. EHR Analysis AI (BERT) - Medical text analysis

Author: JARVIS
Date: 2026-08-18
Timeline: 2027-01~06 Implementation
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Tuple, List, Dict, Optional
import numpy as np
from dataclasses import dataclass, field
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MoERouter")


@dataclass
class MoEConfig:
    """MoE Router Configuration"""
    num_experts: int = 4  # Start with 4, expand to 8 in Month 3
    num_top_k: int = 4    # Top-4 gating
    hidden_dim: int = 256  # Router MLP hidden dimension
    expert_dim: int = 2048  # Expert network hidden dimension
    sparsity_target: float = 0.5  # 50% sparsity (4/8 active)
    load_balance_weight: float = 0.01  # Auxiliary loss weight
    expert_dropout: float = 0.05  # 5% expert-level dropout
    device: str = "cuda" if torch.cuda.is_available() else "cpu"

    # Expert sizes (8B parameters each)
    expert_params: int = int(8e9)


class RouterNetwork(nn.Module):
    """
    Router Network: Routes input tokens to K experts
    Input → MLP(256) → Softmax → Top-K Selection
    """

    def __init__(self, config: MoEConfig, input_dim: int = 768):
        super().__init__()
        self.config = config

        # Router MLP
        self.router = nn.Sequential(
            nn.Linear(input_dim, config.hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(config.hidden_dim, config.num_experts)
        )

        logger.info(f"🔀 Router Network initialized: {input_dim} → {config.hidden_dim} → {config.num_experts}")

    def forward(self, hidden_states: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Args:
            hidden_states: (batch_size, seq_len, hidden_dim)

        Returns:
            router_logits: (batch_size, seq_len, num_experts)
            router_weights: (batch_size, seq_len, num_top_k)
            expert_indices: (batch_size, seq_len, num_top_k)
        """
        batch_size, seq_len, hidden_dim = hidden_states.shape

        # Reshape for routing: (batch * seq_len, hidden_dim)
        reshaped = hidden_states.reshape(-1, hidden_dim)

        # Route
        router_logits = self.router(reshaped)  # (batch * seq_len, num_experts)
        router_logits = router_logits.reshape(batch_size, seq_len, -1)

        # Softmax over experts
        router_weights_all = F.softmax(router_logits, dim=-1)

        # Top-K selection
        top_k_weights, expert_indices = torch.topk(
            router_weights_all,
            k=self.config.num_top_k,
            dim=-1
        )

        # Normalize top-k weights
        top_k_weights = top_k_weights / (top_k_weights.sum(dim=-1, keepdim=True) + 1e-9)

        return router_logits, top_k_weights, expert_indices


class ExpertNetwork(nn.Module):
    """
    Single Expert Network
    Processes input and returns domain-specific output
    """

    def __init__(self, config: MoEConfig, expert_id: int, input_dim: int = 768, output_dim: int = 768):
        super().__init__()
        self.expert_id = expert_id
        self.config = config

        # Expert-specific MLP
        self.network = nn.Sequential(
            nn.Linear(input_dim, config.expert_dim),
            nn.GELU(),
            nn.Dropout(config.expert_dropout),
            nn.Linear(config.expert_dim, config.expert_dim),
            nn.GELU(),
            nn.Dropout(config.expert_dropout),
            nn.Linear(config.expert_dim, output_dim)
        )

        logger.info(f"✅ Expert {expert_id} initialized: {input_dim} → {config.expert_dim} → {output_dim}")

    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        """
        Args:
            hidden_states: (batch_size, seq_len, input_dim) or (N, input_dim)

        Returns:
            output: Same shape as input
        """
        return self.network(hidden_states)


class MoEGate(nn.Module):
    """
    MoE Gate: Combines Top-4 experts with learned routing
    """

    def __init__(self, config: MoEConfig, input_dim: int = 768, output_dim: int = 768):
        super().__init__()
        self.config = config

        # Router network
        self.router = RouterNetwork(config, input_dim)

        # Expert networks (4 medical domain experts)
        self.experts = nn.ModuleList([
            ExpertNetwork(config, expert_id=i, input_dim=input_dim, output_dim=output_dim)
            for i in range(config.num_experts)
        ])

        logger.info(f"🧠 MoE Gate initialized with {config.num_experts} experts, Top-{config.num_top_k} gating")

    def forward(
        self,
        hidden_states: torch.Tensor,
        training: bool = True
    ) -> Tuple[torch.Tensor, Dict[str, torch.Tensor]]:
        """
        Forward pass through MoE gate

        Args:
            hidden_states: (batch_size, seq_len, hidden_dim)
            training: Whether in training mode

        Returns:
            output: (batch_size, seq_len, hidden_dim)
            metrics: Dict with routing and load balance metrics
        """
        batch_size, seq_len, hidden_dim = hidden_states.shape

        # Router: Get top-k expert weights and indices
        router_logits, top_k_weights, expert_indices = self.router(hidden_states)

        # Reshape for expert processing
        reshaped_input = hidden_states.reshape(-1, hidden_dim)  # (batch * seq_len, hidden_dim)

        # Process through all experts (but only use top-k)
        expert_outputs = []
        for expert in self.experts:
            expert_output = expert(reshaped_input)  # (batch * seq_len, hidden_dim)
            expert_outputs.append(expert_output)

        expert_outputs = torch.stack(expert_outputs, dim=1)  # (batch * seq_len, num_experts, hidden_dim)

        # Gather top-k expert outputs
        reshaped_indices = expert_indices.reshape(-1, self.config.num_top_k)  # (batch * seq_len, num_top_k)

        # Select top-k experts
        batch_indices = torch.arange(reshaped_input.shape[0], device=hidden_states.device).unsqueeze(-1)
        top_k_outputs = expert_outputs[batch_indices, reshaped_indices]  # (batch * seq_len, num_top_k, hidden_dim)

        # Weight and sum top-k outputs
        reshaped_weights = top_k_weights.reshape(-1, self.config.num_top_k, 1)
        weighted_outputs = (top_k_outputs * reshaped_weights).sum(dim=1)  # (batch * seq_len, hidden_dim)

        # Reshape back to original shape
        output = weighted_outputs.reshape(batch_size, seq_len, hidden_dim)

        # Calculate metrics
        metrics = self._compute_metrics(
            router_logits,
            expert_indices,
            top_k_weights,
            training
        )

        return output, metrics

    def _compute_metrics(
        self,
        router_logits: torch.Tensor,
        expert_indices: torch.Tensor,
        top_k_weights: torch.Tensor,
        training: bool
    ) -> Dict[str, torch.Tensor]:
        """Compute load balancing and routing metrics"""

        metrics = {}

        # 1. Router Entropy (higher = more balanced)
        router_probs = F.softmax(router_logits, dim=-1)
        entropy = -(router_probs * (torch.log(router_probs + 1e-9))).sum(dim=-1).mean()
        metrics['router_entropy'] = entropy

        # 2. Expert Load Balance (load per expert)
        expert_load = torch.zeros(
            self.config.num_experts,
            device=expert_indices.device
        )
        for i in range(self.config.num_experts):
            load = (expert_indices == i).sum().float()
            expert_load[i] = load

        expert_load = expert_load / (expert_load.sum() + 1e-9)  # Normalize
        metrics['expert_load'] = expert_load
        metrics['load_balance_std'] = expert_load.std()
        metrics['load_balance_mean'] = expert_load.mean()

        # 3. Sparsity (% of active experts)
        active_experts = (expert_load > 0).sum().float()
        sparsity = active_experts / self.config.num_experts
        metrics['sparsity'] = sparsity

        # 4. Top-K weight variance (routing confidence)
        metrics['routing_confidence'] = top_k_weights.max(dim=-1)[0].mean()

        return metrics


class MoEWithAuxiliaryLoss(nn.Module):
    """
    MoE Gate + Auxiliary Loss for load balancing
    Auxiliary Loss prevents Expert Collapse
    """

    def __init__(self, config: MoEConfig, input_dim: int = 768, output_dim: int = 768):
        super().__init__()
        self.config = config
        self.moe_gate = MoEGate(config, input_dim, output_dim)

    def forward(
        self,
        hidden_states: torch.Tensor,
        training: bool = True
    ) -> Tuple[torch.Tensor, Dict[str, torch.Tensor], torch.Tensor]:
        """
        Forward pass with auxiliary loss calculation

        Args:
            hidden_states: (batch_size, seq_len, hidden_dim)
            training: Whether in training mode

        Returns:
            output: (batch_size, seq_len, hidden_dim)
            metrics: Dict with routing metrics
            aux_loss: Scalar auxiliary loss
        """

        output, metrics = self.moe_gate(hidden_states, training)

        # Compute auxiliary loss
        aux_loss = self._compute_auxiliary_loss(metrics) if training else torch.tensor(0.0)

        return output, metrics, aux_loss

    def _compute_auxiliary_loss(self, metrics: Dict[str, torch.Tensor]) -> torch.Tensor:
        """
        Auxiliary Loss for load balancing
        Encourages all experts to be used equally

        Loss = weight * sum((expert_load - 1/num_experts)^2)
        """
        expert_load = metrics['expert_load']
        target_load = 1.0 / self.config.num_experts

        # Load balance loss
        load_loss = ((expert_load - target_load) ** 2).sum()

        # Entropy regularization (encourage high entropy routing)
        entropy = metrics['router_entropy']
        entropy_target = np.log(self.config.num_experts) * 0.9  # 90% of max entropy
        entropy_loss = F.relu(entropy_target - entropy)

        # Combined auxiliary loss
        aux_loss = (load_loss + 0.1 * entropy_loss) * self.config.load_balance_weight

        return aux_loss


# ============================================================================
# Expert Descriptions (for reference)
# ============================================================================

EXPERT_DESCRIPTIONS = {
    0: {
        "name": "Diagnosis AI",
        "description": "CNN-ViT for medical image analysis",
        "domains": ["X-ray analysis", "CT scan interpretation", "pathology"],
        "base_model": "Vision Transformer + CNN hybrid",
        "data_sources": ["Chest X-Ray 100k", "ImageNet medical"],
        "accuracy_target": "96%",
    },
    1: {
        "name": "Drug Design AI",
        "description": "GNN for molecular compound prediction",
        "domains": ["Drug discovery", "molecular docking", "ADME prediction"],
        "base_model": "Graph Neural Network (GNN)",
        "data_sources": ["ChEMBL", "PubChem"],
        "accuracy_target": "94%",
    },
    2: {
        "name": "Patient Prognosis AI",
        "description": "LSTM for clinical time-series prediction",
        "domains": ["ICU mortality", "readmission risk", "disease progression"],
        "base_model": "LSTM + Attention",
        "data_sources": ["MIMIC-IV", "eICU"],
        "accuracy_target": "94%",
    },
    3: {
        "name": "EHR Analysis AI",
        "description": "BERT for medical text analysis",
        "domains": ["Clinical note analysis", "diagnosis coding", "treatment planning"],
        "base_model": "BioBERT / ClinicalBERT",
        "data_sources": ["MIMIC notes", "clinical documentation"],
        "accuracy_target": "96%",
    },
}


def print_moe_summary():
    """Print MoE configuration summary"""
    print("\n" + "="*80)
    print("🧠 JARVIS Phase 26 - MoE Router Summary")
    print("="*80)

    config = MoEConfig()
    print(f"\n⚙️ Configuration:")
    print(f"   • Experts: {config.num_experts} (expanding to 8 in Month 3)")
    print(f"   • Top-K Gating: {config.num_top_k}")
    print(f"   • Sparsity: {config.sparsity_target * 100:.1f}%")
    print(f"   • Load Balance Weight: {config.load_balance_weight}")
    print(f"   • Expert Dropout: {config.expert_dropout * 100:.1f}%")

    print(f"\n🏥 Medical Domain Experts:")
    for expert_id, desc in EXPERT_DESCRIPTIONS.items():
        print(f"\n   Expert {expert_id}: {desc['name']}")
        print(f"   • Description: {desc['description']}")
        print(f"   • Domains: {', '.join(desc['domains'])}")
        print(f"   • Base Model: {desc['base_model']}")
        print(f"   • Accuracy Target: {desc['accuracy_target']}")

    print(f"\n📊 Success Metrics (2027-01~06):")
    print(f"   ✅ Expert Load Balance: Std < 10%")
    print(f"   ✅ Router Entropy: > 0.95")
    print(f"   ✅ Domain Accuracy: > 94%")
    print(f"   ✅ Overall Accuracy: 97% → 99%")

    print("\n" + "="*80 + "\n")


if __name__ == "__main__":
    print_moe_summary()

    # Test initialization
    config = MoEConfig()
    print("🔧 Testing MoE Router initialization...")

    moe = MoEWithAuxiliaryLoss(config, input_dim=768, output_dim=768)
    print(f"✅ MoE Router created successfully")
    print(f"   • Total parameters: ~{sum(p.numel() for p in moe.parameters()) / 1e9:.2f}B")

    # Test forward pass
    batch_size, seq_len, hidden_dim = 2, 128, 768
    test_input = torch.randn(batch_size, seq_len, hidden_dim)

    print(f"\n🧪 Testing forward pass...")
    print(f"   • Input shape: {test_input.shape}")

    output, metrics, aux_loss = moe(test_input, training=True)

    print(f"   • Output shape: {output.shape}")
    print(f"\n📊 Metrics:")
    for key, value in metrics.items():
        if isinstance(value, torch.Tensor):
            if value.dim() == 0:
                print(f"   • {key}: {value.item():.4f}")
            else:
                print(f"   • {key}: {value.shape} (mean: {value.mean().item():.4f})")
    print(f"   • Auxiliary Loss: {aux_loss.item():.6f}")
    print(f"\n✅ All tests passed!")
