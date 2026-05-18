import chgnet
from pymatgen.core import Structure
import pandas as pd
import numpy as np
from chgnet.model.model import CHGNet
from chgnet.model.dynamics import MolecularDynamics
from chgnet.model import StructOptimizer

"""
#instructions for installation of chgnet:
go to cmd line and create conda env:
conda create -n chgnet
conda activate chgnet
pip install chgnet

**Note, everytime you want to use chgnet, you need to activate the conda env:
conda activate chgnet
then you can run the code.
"""

# adjustable parameters: dopants, and supercell size (concentration)
supercell_size = 2
dopant = "Al" # or "Mn", "Ni"
primitive_cell_file = "primitive_cells/NaCoO2.cif"
nsteps = 1000 #maximum number of steps for the optimizer
relaxation_threshold = 0.01 # eV/Angstrom, the force threshold for the optimizer to stop

# Load specific CHGNet versions
chgnet = CHGNet.load(model_name='r2scan')

primitive_cell = Structure.from_file(primitive_cell_file)
primitive_cell_energy = chgnet.predict_structure(primitive_cell)["e"]

#add dopant to supercell
structure = primitive_cell.make_supercell([supercell_size, supercell_size, supercell_size])
#print("original structure:", structure)
dopant_sites = [i for i, site in enumerate(structure) if site.specie.symbol == "Co"]
print("dopant sites:", dopant_sites)
structure[dopant_sites[5]] = dopant
print("dopant structure:", structure)
print("effective concentration:", 1 / len(dopant_sites))

print(f"original space group: {structure.get_space_group_info()}")


trajectory = StructOptimizer().relax(structure, steps=nsteps,fmax=relaxation_threshold)
print("CHGNet relaxed structure", trajectory["final_structure"])
print("CHGNet relaxed structure space group:", trajectory["final_structure"].get_space_group_info())
print("primitive cell energy in eV/atom:", primitive_cell_energy )
print("relaxed supercell total energy in eV/atom:", trajectory['trajectory'].energies[-1] / len(structure))
trajectory["final_structure"].to_file("relaxed_structures/NaCoO2.cif")
#differences between lowest energy structure and other experimental observed structures < 0.5eV/atom

Celciustemperature=250. # in Celsius

md = MolecularDynamics(
    atoms=structure,
    model=chgnet,
    ensemble="nvt",
    temperature=273.+Celciustemperature,  # in K
    timestep=2,  # in femto-seconds
    trajectory="md_out.traj",
    logfile="md_out.log",
    loginterval=100,
)
md.run(5000)