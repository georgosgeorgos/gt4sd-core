from typing import List, Tuple

import networkx as nx
import numpy as np
import rdkit.Chem as Chem
import torch
import torch_geometric.data as gd
from rdkit.Chem import Mol
from rdkit.Chem.rdchem import BondType, ChiralType

from gt4sd.frameworks.gflownet.envs.graph_building_env import (
    Graph,
    GraphAction,
    GraphActionType,
    GraphBuildingEnvContext,
)


class MolBuildingEnvContext(GraphBuildingEnvContext):
    """A specification of what is being generated for a GraphBuildingEnv

    This context specifies how to create molecules atom-by-atom (and attribute-by-attribute).

    """

    def __init__(self, atoms=["H", "C", "N", "O", "F"], num_cond_dim=0):
        # idx 0 has to coincide with the default value
        self.atom_attr_values = {
            "v": atoms,
            "chi": [
                ChiralType.CHI_UNSPECIFIED,
                ChiralType.CHI_TETRAHEDRAL_CW,
                ChiralType.CHI_TETRAHEDRAL_CCW,
            ],
            "charge": [0, 1, -1],
            "expl_H": list(range(4)),  # TODO: check what is the actual range of this
            "no_impl": [False, True],
        }
        self.atom_attr_defaults = {
            k: self.atom_attr_values[k][0] for k in self.atom_attr_values
        }
        # The size of the input vector for each atom
        self.atom_attr_size = sum(len(i) for i in self.atom_attr_values.values())
        self.atom_attrs = sorted(self.atom_attr_values.keys())
        # The beginning position within the input vector of each attribute
        self.atom_attr_slice = [0] + list(
            np.cumsum([len(self.atom_attr_values[i]) for i in self.atom_attrs])
        )
        # The beginning position within the logit vector of each attribute
        self.atom_attr_logit_slice = {
            k: s
            for k, s in zip(
                self.atom_attrs,
                [0]
                + list(
                    np.cumsum(
                        [len(self.atom_attr_values[i]) - 1 for i in self.atom_attrs]
                    )
                ),
            )
        }
        # The attribute and value each logit dimension maps back to
        self.atom_attr_logit_map = [
            (k, v)
            for k in self.atom_attrs
            if k != "v"
            # index 0 is skipped because it is the default value
            for v in self.atom_attr_values[k][1:]
        ]

        self.bond_attr_values = {
            "type": [
                BondType.SINGLE,
                BondType.DOUBLE,
                BondType.TRIPLE,
                BondType.AROMATIC,
            ],
        }
        self.bond_attr_defaults = {
            k: self.bond_attr_values[k][0] for k in self.bond_attr_values
        }
        self.bond_attr_size = sum(len(i) for i in self.bond_attr_values.values())
        self.bond_attrs = sorted(self.bond_attr_values.keys())
        self.bond_attr_slice = [0] + list(
            np.cumsum([len(self.bond_attr_values[i]) for i in self.bond_attrs])
        )
        self.bond_attr_logit_slice = {
            k: s
            for k, s in zip(
                self.bond_attrs,
                [0]
                + list(
                    np.cumsum(
                        [len(self.bond_attr_values[i]) - 1 for i in self.bond_attrs]
                    )
                ),
            )
        }
        self.bond_attr_logit_map = [
            (k, v) for k in self.bond_attrs for v in self.bond_attr_values[k][1:]
        ]

        # These values are used by Models to know how many inputs/logits to produce
        self.num_new_node_values = len(atoms)
        self.num_node_attr_logits = len(self.atom_attr_logit_map)
        self.num_node_dim = self.atom_attr_size + 1
        self.num_edge_attr_logits = len(self.bond_attr_logit_map)
        self.num_edge_dim = self.bond_attr_size
        self.num_cond_dim = num_cond_dim

        # Order in which models have to output logits
        self.action_type_order = [
            GraphActionType.Stop,
            GraphActionType.AddNode,
            GraphActionType.SetNodeAttr,
            GraphActionType.AddEdge,
            GraphActionType.SetEdgeAttr,
        ]
        self.device = torch.device("cpu")

    def aidx_to_GraphAction(self, g: gd.Data, action_idx: Tuple[int, int, int]):
        """Translate an action index (e.g. from a GraphActionCategorical) to a GraphAction"""
        act_type, act_row, act_col = [int(i) for i in action_idx]
        t = self.action_type_order[act_type]
        if t is GraphActionType.Stop:
            return GraphAction(t)
        elif t is GraphActionType.AddNode:
            return GraphAction(
                t, source=act_row, value=self.atom_attr_values["v"][act_col]
            )
        elif t is GraphActionType.SetNodeAttr:
            attr, val = self.atom_attr_logit_map[act_col]
            return GraphAction(t, source=act_row, attr=attr, value=val)
        elif t is GraphActionType.AddEdge:
            a, b = g.non_edge_index[:, act_row]
            return GraphAction(t, source=a.item(), target=b.item())
        elif t is GraphActionType.SetEdgeAttr:
            a, b = g.edge_index[
                :, act_row * 2
            ]  # Edges are duplicated to get undirected GNN, deduplicated for logits
            attr, val = self.bond_attr_logit_map[act_col]
            return GraphAction(
                t, source=a.item(), target=b.item(), attr=attr, value=val
            )

    def GraphAction_to_aidx(
        self, g: gd.Data, action: GraphAction
    ) -> Tuple[int, int, int]:
        """Translate a GraphAction to an index tuple"""
        if action.action is GraphActionType.Stop:
            row = col = 0
        elif action.action is GraphActionType.AddNode:
            row = action.source
            col = self.atom_attr_values["v"].index(action.value)
        elif action.action is GraphActionType.SetNodeAttr:
            row = action.source
            # - 1 because the default is index 0
            col = (
                self.atom_attr_values[action.attr].index(action.value)
                - 1
                + self.atom_attr_logit_slice[action.attr]
            )
        elif action.action is GraphActionType.AddEdge:
            # Here we have to retrieve the index in non_edge_index of an edge (s,t)
            # that's also possibly in the reverse order (t,s).
            # That's definitely not too efficient, can we do better?
            row = (
                (
                    g.non_edge_index.T == torch.tensor([(action.source, action.target)])
                ).prod(1)
                + (
                    g.non_edge_index.T == torch.tensor([(action.target, action.source)])
                ).prod(1)
            ).argmax()
            col = 0
        elif action.action is GraphActionType.SetEdgeAttr:
            # Here the edges are duplicated, both (i,j) and (j,i) are in edge_index
            # so no need for a double check.
            # row = ((g.edge_index.T == torch.tensor([(action.source, action.target)])).prod(1) +
            #       (g.edge_index.T == torch.tensor([(action.target, action.source)])).prod(1)).argmax()
            row = (
                (g.edge_index.T == torch.tensor([(action.source, action.target)]))
                .prod(1)
                .argmax()
            )
            # Because edges are duplicated but logits aren't, divide by two
            row = row.div(2, rounding_mode="floor")  # type: ignore
            col = (
                self.bond_attr_values[action.attr].index(action.value)
                - 1
                + self.bond_attr_logit_slice[action.attr]
            )
        type_idx = self.action_type_order.index(action.action)
        return (type_idx, int(row), int(col))

    def graph_to_Data(self, g: Graph) -> gd.Data:
        """Convert a networkx Graph to a torch geometric Data instance"""
        x = torch.zeros((max(1, len(g.nodes)), self.num_node_dim))
        x[0, -1] = len(g.nodes) == 0
        for i, n in enumerate(g.nodes):
            ad = g.nodes[n]
            for k, sl in zip(self.atom_attrs, self.atom_attr_slice):
                idx = self.atom_attr_values[k].index(ad[k]) if k in ad else 0
                x[i, sl + idx] = 1
        edge_attr = torch.zeros((len(g.edges) * 2, self.num_edge_dim))
        for i, e in enumerate(g.edges):
            ad = g.edges[e]
            for k, sl in zip(self.bond_attrs, self.bond_attr_slice):
                idx = self.bond_attr_values[k].index(ad[k]) if k in ad else 0
                edge_attr[i * 2, sl + idx] = 1
                edge_attr[i * 2 + 1, sl + idx] = 1
        edge_index = (
            torch.tensor(
                [e for i, j in g.edges for e in [(i, j), (j, i)]], dtype=torch.long
            )
            .reshape((-1, 2))
            .T
        )
        gc = nx.complement(g)
        # non_edge_index = torch.tensor([i for i in gc.edges], dtype=torch.long)
        non_edge_index = torch.tensor(
            [i for i in gc.edges], dtype=torch.long
        ).T.reshape((2, -1))
        # non_edge_index = torch.tensor([i for i in gc.edges], dtype=torch.long).permute(0, 2, 1).reshape((2, -1))
        return gd.Data(x, edge_index, edge_attr, non_edge_index=non_edge_index)

    def collate(self, graphs: List[gd.Data]):
        """Batch Data instances"""
        return gd.Batch.from_data_list(
            graphs, follow_batch=["edge_index", "non_edge_index"]
        )

    def mol_to_graph(self, mol: Mol) -> Graph:
        """Convert an RDMol to a Graph"""
        g = Graph()
        # Only set an attribute tag if it is not the default attribute
        for a in mol.GetAtoms():
            attrs = {
                "chi": a.GetChiralTag(),
                "charge": a.GetFormalCharge(),
                "expl_H": a.GetNumExplicitHs(),
                "no_impl": a.GetNoImplicit(),
            }
            g.add_node(
                a.GetIdx(),
                v=a.GetSymbol(),
                **{
                    attr: val
                    for attr, val in attrs.items()
                    if val != self.atom_attr_defaults[attr]
                },
            )
        for b in mol.GetBonds():
            attrs = {"type": b.GetBondType()}
            g.add_edge(
                b.GetBeginAtomIdx(),
                b.GetEndAtomIdx(),
                **{
                    attr: val
                    for attr, val in attrs.items()
                    if val != self.bond_attr_defaults[attr]
                },
            )
        return g

    def graph_to_mol(self, g: Graph) -> Mol:
        mp = Chem.RWMol()
        mp.BeginBatchEdit()
        for i in range(len(g.nodes)):
            d = g.nodes[i]
            a = Chem.Atom(d["v"])
            if "chi" in d:
                a.SetChiralTag(d["chi"])
            if "charge" in d:
                a.SetFormalCharge(d["charge"])
            if "expl_H" in d:
                a.SetNumExplicitHs(d["expl_H"])
            if "no_impl" in d:
                a.SetNoImplicit(d["no_impl"])
            mp.AddAtom(a)
        for e in g.edges:
            d = g.edges[e]
            mp.AddBond(e[0], e[1], d.get("type", BondType.SINGLE))
        mp.CommitBatchEdit()
        Chem.SanitizeMol(mp)
        return mp

    def is_sane(self, g: Graph) -> bool:
        try:
            mol = self.graph_to_mol(g)
            assert Chem.MolFromSmiles(Chem.MolToSmiles(mol)) is not None
        except Exception:
            return False
        if mol is None:
            return False
        return True
