# Protocols

The five seams of the package, as `typing.Protocol` definitions. Implementations are **structural**
— nothing subclasses these — so the behavioural contract is stated once, here, and each
implementation's own docstring says what it does differently rather than restating the interface.

One implementation per protocol is the right number for now. The seam is the point, not the number
of implementations.

::: lczkit.protocols

## Coordinate reference system

All internal computation happens in a projected CRS. This is checked on entry to each stage rather
than left as a convention, because a geographic CRS makes every area statistic meaningless without
raising anything.

::: lczkit.crs
