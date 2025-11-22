import owon_psu
from owon_psu import OwonPSU
import inspect

print("METHODS:\n")
for name, func in inspect.getmembers(OwonPSU, inspect.isfunction):
    print(name)
