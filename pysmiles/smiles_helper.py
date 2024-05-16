# -*- coding: utf-8 -*-
# Copyright 2018 Peter C Kroon

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Contains helper functions for parsing and writing SMILES strings, as well as
some convenience functions for adding hydrogens, and detecting aromaticity.
"""

import logging
import re
import operator

import networkx as nx

LOGGER = logging.getLogger(__name__)

ISOTOPE_PATTERN = r'(?P<isotope>[\d]+)?'
ELEMENT_PATTERN = r'(?P<element>b|c|n|o|s|p|as|se|\*|[A-Z][a-z]{0,2})'
STEREO_PATTERN = r'(?P<stereo>@|@@|@TH[1-2]|@AL[1-2]|@SP[1-3]|@OH[\d]{1,2}|'\
                  r'@TB[\d]{1,2})?'
HCOUNT_PATTERN = r'(?P<hcount>H[\d]?)?'
CHARGE_PATTERN = r'(?P<charge>(-|\+)(\++|-+|[\d]{1,2})?)?'
CLASS_PATTERN = r'(?::(?P<class>[\d]+))?'
ATOM_PATTERN = re.compile(r'^\[' + ISOTOPE_PATTERN + ELEMENT_PATTERN +
                          STEREO_PATTERN + HCOUNT_PATTERN + CHARGE_PATTERN +
                          CLASS_PATTERN + r'\]$')

AROMATIC_ATOMS = "B C N O P S Se As *".split()

ORBITAL_SIZES = [[2],  # 1s
                 [2,  6],  # 2s, 2p
                 [2,  6],  # 3s, 3p
                 [2,  10, 6],  # 4s, 3d, 4p
                 [2,  10, 6],  # 5s, 4d, 5p
                 [2,  14, 10, 6],]  # 6s, 4f, 5d, 6p

ELECTRON_COUNTS = {"H": 1, "B": 5, "C": 6, "N": 7, "O": 8, "F": 9, "P": 15,
                   "S": 16, "Cl": 17, "As": 33, "Se": 34, "Br": 35, "I": 53}


def parse_atom(atom):
    """
    Parses a SMILES atom token, and returns a dict with the information.

    Note
    ----
    Can not deal with stereochemical information yet. This gets discarded.

    Parameters
    ----------
    atom : str
        The atom string to interpret. Looks something like one of the
        following: "C", "c", "[13CH3-1:2]"

    Returns
    -------
    dict
        A dictionary containing at least 'element', 'aromatic', and 'charge'. If
        present, will also contain 'hcount', 'isotope', and 'class'.
    """
    defaults = {'charge': 0, 'hcount': 0, 'aromatic': False}
    if not atom.startswith('[') and not atom.endswith(']'):
        if atom != '*':
            # Don't specify hcount to signal we don't actually know anything
            # about it
            return {'element': atom.capitalize(), 'charge': 0,
                    'aromatic': atom.islower()}
        else:
            return defaults.copy()
    match = ATOM_PATTERN.match(atom)
    if match is None:
        raise ValueError('The atom {} is malformatted'.format(atom))
    out = defaults.copy()
    out.update({k: v for k, v in match.groupdict().items() if v is not None})

    if out.get('element', 'X').islower():
        out['aromatic'] = True

    parse_helpers = {
        'isotope': int,
        'element': str.capitalize,
        'stereo': lambda x: x,
        'hcount': parse_hcount,
        'charge': parse_charge,
        'class': int,
        'aromatic': lambda x: x,
    }

    for attr, val_str in out.items():
        out[attr] = parse_helpers[attr](val_str)

    if out['element'] == '*':
        del out['element']

    if out.get('element') == 'H' and out.get('hcount', 0):
        raise ValueError("A hydrogen atom can't have hydrogens")

    if 'stereo' in out:
        LOGGER.warning('Atom "%s" contains stereochemical information that will be discarded.', atom)

    return out


def format_atom(molecule, node_key, default_element='*'):
    """
    Formats a node following SMILES conventions. Uses the attributes `element`,
    `charge`, `hcount`, `stereo`, `isotope` and `class`.

    Parameters
    ----------
    molecule : nx.Graph
        The molecule containing the atom.
    node_key : hashable
        The node key of the atom in `molecule`.
    default_element : str
        The element to use if the attribute is not present in the node.

    Returns
    -------
    str
        The atom as SMILES string.
    """
    node = molecule.nodes[node_key]
    name = node.get('element', default_element)
    charge = node.get('charge', 0)
    hcount = node.get('hcount', 0)
    stereo = node.get('stereo', None)
    isotope = node.get('isotope', '')
    class_ = node.get('class', '')
    aromatic = node.get('aromatic', False)
    default_h = has_default_h_count(molecule, node_key)

    if stereo is not None:
        raise NotImplementedError

    if aromatic:
        name = name.lower()

    if (stereo is None and isotope == '' and charge == 0 and default_h and class_ == '' and
            (name.lower() in 'b c n o p s *'.split() or name in 'F Cl Br I'.split())):
        return name

    if hcount:
        hcountstr = 'H'
        if hcount > 1:
            hcountstr += str(hcount)
    else:
        hcountstr = ''

    if charge > 0:
        chargestr = '+'
        if charge > 1:
            chargestr += str(charge)
    elif charge < 0:
        chargestr = '-'
        if charge < -1:
            chargestr += str(-charge)
    else:
        chargestr = ''

    if class_ != '':
        class_ = ':{}'.format(class_)
    fmt = '[{isotope}{name}{stereo}{hcount}{charge}{class_}]'
    return fmt.format(isotope=isotope, name=name, stereo='', hcount=hcountstr,
                      charge=chargestr, class_=class_)


def parse_hcount(hcount_str):
    """
    Parses a SMILES hydrogen count specifications.

    Parameters
    ----------
    hcount_str : str
        The hydrogen count specification to parse.

    Returns
    -------
    int
        The number of hydrogens specified.
    """
    if not hcount_str:
        return 0
    if hcount_str == 'H':
        return 1
    return int(hcount_str[1:])


def parse_charge(charge_str):
    """
    Parses a SMILES charge specification.

    Parameters
    ----------
    charge_str : str
        The charge specification to parse.

    Returns
    -------
    int
        The charge.
    """
    if not charge_str:
        return 0
    signs = {'-': -1, '+': 1}
    sign = signs[charge_str[0]]
    if len(charge_str) > 1 and charge_str[1].isdigit():
        charge = sign * int(charge_str[1:])
    else:
        charge = sign * charge_str.count(charge_str[0])
    return charge


def add_explicit_hydrogens(mol):
    """
    Adds explicit hydrogen nodes to `mol`, the amount is determined by the node
    attribute 'hcount'. Will remove the 'hcount' attribute.

    Parameters
    ----------
    mol : nx.Graph
        The molecule to which explicit hydrogens should be added. Is modified
        in-place.

    Returns
    -------
    None
        `mol` is modified in-place.
    """
    h_atom = parse_atom('[H]')
    if 'hcount' in h_atom:
        del h_atom['hcount']
    for n_idx in list(mol.nodes):
        hcount = mol.nodes[n_idx].get('hcount', 0)
        idxs = range(max(mol) + 1, max(mol) + hcount + 1)
        # Get the defaults from parse_atom.
        mol.add_nodes_from(idxs, **h_atom.copy())
        mol.add_edges_from([(n_idx, jdx) for jdx in idxs], order=1)
        if 'hcount' in mol.nodes[n_idx]:
            del mol.nodes[n_idx]['hcount']


def remove_explicit_hydrogens(mol):
    """
    Removes all explicit, simple hydrogens from `mol`. Simple means it is
    identical to the SMILES string "[H]", and has exactly one bond. Increments
    'hcount' where appropriate.

    Parameters
    ----------
    mol : nx.Graph
        The molecule whose explicit hydrogens should be removed. Is modified
        in-place.

    Returns
    -------
    None
        `mol` is modified in-place.
    """
    to_remove = set()
#    defaults = parse_atom('[H]')
    for n_idx in mol.nodes:
        node = mol.nodes[n_idx]
        neighbors = list(mol[n_idx])
        # TODO: get these defaults from parsing [H]. But do something smart
        #       with the hcount attribute.
        if (node.get('charge', 0) == 0 and node.get('element', '') == 'H' and
                'isotope' not in node and node.get('class', 0) == 0 and
                len(neighbors) == 1):
            neighbor = neighbors[0]
            if (mol.nodes[neighbor].get('element', '') == 'H' or
                    mol.edges[n_idx, neighbor].get('order', 1) != 1):
                # The molecule is H2, or the bond order is not 1.
                continue
            to_remove.add(n_idx)
            mol.nodes[neighbor]['hcount'] = mol.nodes[neighbor].get('hcount', 0) + 1
    mol.remove_nodes_from(to_remove)
    for n_idx in mol.nodes:
        if 'hcount' not in mol.nodes[n_idx]:
            mol.nodes[n_idx]['hcount'] = 0


def fill_valence(mol, respect_hcount=True, respect_bond_order=True,
                 max_bond_order=3):
    """
    Sets the attribute 'hcount' on all nodes in `mol` that don't have it yet.
    The value to which it is set is based on the node's 'element', and the
    number of bonds it has. Default valences are as specified by the global
    variable VALENCES.

    Parameters
    ----------
    mol : nx.Graph
        The molecule whose nodes should get a 'hcount'. Is modified in-place.
    respect_hcount : bool
        If True, don't change the hcount on nodes that already have it set.
    respect_bond_order : bool
        If False, first try to fill the valence by increasing bond orders, and
        add hydrogens after.
    max_bond_order : number
        Only meaningful if respect_bond_order is False. This is the highest
        bond order that will be set.

    Returns
    -------
    None
        `mol` is modified in-place.
    """
    if not respect_bond_order:
        increment_bond_orders(mol, max_bond_order=max_bond_order)
    for n_idx in mol:
        node = mol.nodes[n_idx]
        if 'hcount' in node and respect_hcount:
            continue
        missing = max(bonds_missing(mol, n_idx), 0)
        node['hcount'] = node.get('hcount', 0) + missing


def bonds_missing(mol, node_idx, use_order=True):
    """
    Returns how much the specified node is under valence. If use_order is
    False, treat all bonds as if they are order 1.

    Parameters
    ----------
    mol : nx.Graph
        The molecule.
    node_idx : hashable
        The node to look at. Should be in mol.
    use_order : bool
        If False, treat all bonds as single.

    Returns
    -------
    int
        The number of missing bonds.
    """
    bonds = _bonds(mol, node_idx, use_order)
    bonds += mol.nodes[node_idx].get('hcount', 0)

    val = valence(mol.nodes[node_idx])
    val = [v for v in val if v >= bonds] or [0]
    return int(max(val[0] - bonds, 0))


def valence(atom):
    """
    Returns the valence of the atom. Since some elements can have
    multiple valences, The valence is returned as list.

    Parameters
    ----------
    atom: dict

    Returns
    -------
    list[int]
        The valences for the given atom.
    """
    electrons = ELECTRON_COUNTS.get(atom.get('element', '*').capitalize(), 0) - atom.get('charge', 0)
    # Let's start by filling complete shells:
    for idx, shell in enumerate(ORBITAL_SIZES):
        shell_size = sum(shell)
        if shell_size <= electrons:
            electrons -= shell_size
        else:
            break
    else:  # nobreak
        raise ValueError(f'Too many electrons for sanity for {atom}: {electrons+sum(map(sum, ORBITAL_SIZES))}')
    # Any electrons we have leftover we distribute over the orbitals. First 1
    # electron in each, then we start making pairs. The resulting valence will
    # be the number of unpaired electrons. Added bonus/complication: electrons
    # in pairs we can excite to higher shells, increasing the number of unpaired
    # electrons
    shell = ORBITAL_SIZES[idx]
    shell_size = sum(shell)
    to_assign = min(electrons, shell_size // 2)
    single_electrons = to_assign
    electrons -= to_assign

    to_assign = min(electrons, shell_size // 2)
    electron_pairs = to_assign
    single_electrons -= to_assign
    electrons -= to_assign
    assert electrons == 0

    if len(ORBITAL_SIZES[idx+1]) >= 3:
        val = [single_electrons + 2*n for n in range(electron_pairs+1)]
    else:
        val = [single_electrons]

    return val


def _bonds(mol, node_idx, use_order=True):
    """
    Returns how many explicit bonds the specified node has. If use_order is
    False, treat all bonds as if they are order 1.

    Parameters
    ----------
    mol : nx.Graph
        The molecule.
    node_idx : hashable
        The node to look at. Should be in mol.
    use_order : bool
        If False, treat all bonds as single.

    Returns
    -------
    int
        The number of bonds.
    """
    if use_order:
        bond_orders = map(operator.itemgetter(2),
                          mol.edges(nbunch=node_idx, data='order', default=1))
        bonds = sum(bond_orders)
    else:
        bonds = len(mol[node_idx])
    return bonds


def has_default_h_count(mol, node_idx, use_order=True):
    """
    Returns whether the hydrogen count for this atom is non-standard.

    Parameters
    ----------
    mol : nx.Graph
        The molecule.
    node_idx : hashable
        The node to look at. Should be in mol.
    use_order : bool
        If False, treat all bonds as single.

    Returns
    -------
    bool
    """
    bonds = _bonds(mol, node_idx, use_order)
    val = valence(mol.nodes[node_idx])
    val = [v for v in val if v >= bonds] or [0]
    hcount = mol.nodes[node_idx].get('hcount', 0)
    return max(val[0] - bonds, 0) == hcount


def _prune_nodes(nodes, mol):
    new_nodes = []
    for node in nodes:
        # all wild card nodes are eligible
        if mol.nodes[node].get('element', '*') == '*':
            new_nodes.append(node)
            continue
        missing = bonds_missing(mol, node, use_order=True)
        if missing > 0:
            new_nodes.append(node)
    return mol.subgraph(new_nodes)


def mark_aromatic_atoms(mol, atoms=None):
    """
    Properly kekeulizes molecules and sets the aromatic attribute.

    Parameters
    ----------
    mol : nx.Graph
        The molecule.
    atoms: collections.abc.Iterable
        The atoms to act on; all other nodes are pruned

    Returns
    -------
    None
        `mol` is modified in-place.
    """
    if atoms is None:
        atoms = set(mol.nodes)
    # prune all nodes from molecule that are eligible and have
    # full valency
    ds_graph = _prune_nodes(atoms, mol)

    # set the aromatic attribute to False for all nodes
    # as a precaution
    nx.set_node_attributes(mol, False, 'aromatic')

    for sub_ds in nx.connected_components(ds_graph):
        sub_ds_graph = mol.subgraph(sub_ds)
        max_match = nx.max_weight_matching(sub_ds_graph)
        # we check if a maximum matching exists and
        # if it is perfect. if it is not perfect,
        # this graph originates from a completely invalid
        # smiles and we raise an error
        if not nx.is_perfect_matching(sub_ds_graph, max_match):
            msg = "Your molecule is invalid and cannot be kekulized."
            raise SyntaxError(msg)

        # we consider a node aromatic if it can take part in DIME
        # to do so all nodes in a delocalized subgraph have to be
        # part of a cycle system
        cycles = nx.cycle_basis(sub_ds_graph)
        nodes_in_cycles = []
        for cycle in cycles:
            nodes_in_cycles += cycle
            nx.set_node_attributes(mol, {node: True for node in cycle}, 'aromatic')

        for node in sub_ds_graph.nodes:
            if node not in nodes_in_cycles:
                mol.nodes[node]['aromatic'] = False

        for edge in max_match:
            if not edge[0] in nodes_in_cycles and not edge[1] in nodes_in_cycles:
                mol.edges[edge]['order'] = 2

def mark_aromatic_edges(mol):
    """
    Set all bonds between aromatic atoms (attribute 'aromatic' is `True`) to
    1.5. Gives all other bonds that don't have an order yet an order of 1.

    Parameters
    ----------
    mol : nx.Graph
        The molecule.

    Returns
    -------
    None
        `mol` is modified in-place.
    """
    for edge in mol.edges:
        if all(mol.nodes[node].get('aromatic', 'False') for node in edge):
            mol.edges[edge]['order'] = 1.5
        elif 'order' not in mol.edges[edge]:
            mol.edges[edge]['order'] = 1

def correct_aromatic_rings(mol):
    """
    Sets hcount for all atoms, marks aromaticity for all atoms, and the order of
    all aromatic bonds to 1.5.

    Parameters
    ----------
    mol : nx.Graph
        The molecule.

    Returns
    -------
    None
        `mol` is modified in-place.
    """
    fill_valence(mol)
    mark_aromatic_atoms(mol, atoms=mol.nodes)
    mark_aromatic_edges(mol)


def increment_bond_orders(molecule, max_bond_order=3):
    """
    Increments bond orders up to what the atom's valence allows.

    Parameters
    ----------
    molecule : nx.Graph
        The molecule to process.
    max_bond_order : number
        The highest bond order allowed to make.

    Returns
    -------
    None
        molecule is modified in-place.
    """
    # Gather the number of open spots for all atoms beforehand, since some
    # might have multiple oxidation states (e.g. S). We don't want to change
    # oxidation state halfway through for some funny reason. It shouldn't be
    # nescessary, but it can't hurt.
    missing_bonds = {}
    for idx in molecule:
        missing_bonds[idx] = max(bonds_missing(molecule, idx), 0)

    for idx, jdx in molecule.edges:
        missing_idx = missing_bonds[idx]
        missing_jdx = missing_bonds[jdx]
        edge_missing = min(missing_idx, missing_jdx)
        current_order = molecule.edges[idx, jdx].get("order", 1)
        if current_order == 1.5:
            continue
        new_order = edge_missing + current_order
        new_order = min(new_order, max_bond_order)
        molecule.edges[idx, jdx]['order'] = new_order
        missing_bonds[idx] -= edge_missing
        missing_bonds[jdx] -= edge_missing
