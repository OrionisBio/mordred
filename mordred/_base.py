from rdkit import Chem
from rdkit.Chem.rdPartialCharges import ComputeGasteigerCharges
from six import with_metaclass
from abc import ABCMeta, abstractmethod
from types import ModuleType

try:
    from inspect import getfullargspec as getargspec
except ImportError:
    from inspect import getargspec


__all__ =\
    'Calculator',\
    'Descriptor',


class Key(object):
    __slots__ = 'cls', 'args'

    def __init__(self, cls, *args):
        assert isinstance(cls, type)
        self.cls = cls
        self.args = args

    def __hash__(self):
        return hash((self.cls, self.args))

    def __eq__(self, other):
        return self.cls is other.cls and self.args == other.args

    def __ne__(self, other):
        return self.cls is not other.cls or self.args != other.args

    def __str__(self):
        return self.cls.__name__ + str(hash(tuple(self.args)))

    def __repr__(self):
        return 'Key({!r}, *{!r})'.format(self.cls, self.args)

    def create(self):
        try:
            return self.cls(*self.args)
        except TypeError:
            raise ValueError('cannot create {!r} by {!r}'.format(self.cls, self.args))

    @property
    def descriptor_key(self):
        return self


class Descriptor(with_metaclass(ABCMeta, object)):
    explicit_hydrogens = True
    gasteiger_charges = False
    kekulize = False

    @classmethod
    def preset(cls):
        yield cls()

    @classmethod
    def make_key(cls, *args):
        return Key(cls, *args)

    @property
    def dependencies(self):
        return None

    @property
    def descriptor_key(self):
        return self.make_key()

    @property
    def descriptor_name(self):
        return str(self.descriptor_key)

    @abstractmethod
    def calculate(self, mol):
        pass

    def __call__(self, mol):
        return next(Calculator(self)(mol))[1]


class Molecule(object):
    def __init__(self, orig):
        Chem.Kekulize(orig)
        self.orig = orig
        self.cache = dict()

    def key(self, explicitH=True, kekulize=False, gasteiger=False):
        return (explicitH, kekulize, gasteiger)

    def hydration(self, explicitH):
        key = self.key(explicitH=explicitH)
        if key in self.cache:
            return self.cache[key]

        mol = Chem.AddHs(self.orig) if explicitH else Chem.RemoveHs(self.orig)
        self.cache[key] = mol
        return mol

    def kekulize(self, explicitH):
        key = self.key(explicitH=explicitH, kekulize=True)
        if key in self.cache:
            return self.cache[key]

        mol = Chem.Mol(self.hydration(explicitH))
        Chem.Kekulize(mol)
        self.cache[key] = mol
        return mol

    def gasteiger(self, explicitH, kekulize):
        key = self.key(explicitH=explicitH, kekulize=kekulize, gasteiger=True)
        if key in self.cache:
            return self.cache[key]

        mol = self.kekulize(explicitH) if kekulize else self.hydration(explicitH)
        ComputeGasteigerCharges(mol)
        self.cache[key] = mol
        return mol

    def get(self, explicitH, kekulize, gasteiger):
        key = self.key(explicitH=explicitH, kekulize=kekulize, gasteiger=gasteiger)
        if key in self.cache:
            return self.cache[key]

        if gasteiger:
            return self.gasteiger(explicitH, kekulize)
        elif kekulize:
            return self.kekulize(explicitH)
        else:
            return self.hydration(explicitH)


class Calculator(object):
    def __init__(self, *descs):
        self.descriptors = []
        self.explicitH = False
        self.gasteiger = False
        self.kekulize = False

        self.register(*descs)

    def _register_one(self, desc):
        if not isinstance(desc, Descriptor):
            raise ValueError('{!r} is not descriptor'.format(desc))

        self.descriptors.append(desc)

        if desc.explicit_hydrogens:
            self.explicitH = True

        if desc.gasteiger_charges:
            self.gasteiger = True

        if desc.kekulize:
            self.kekulize = True

    def register(self, *descs):
        for desc in descs:
            if not hasattr(desc, '__iter__'):
                if isinstance(desc, type):
                    for d in desc.preset():
                        self._register_one(d)

                elif isinstance(desc, ModuleType):
                    for name in dir(desc):
                        if name[:1] == '_':
                            continue

                        d = getattr(desc, name)
                        if issubclass(d, Descriptor):
                            self.register(d)

                else:
                    self._register_one(desc)

            elif isinstance(desc, tuple) and isinstance(desc[0], type):
                self._register_one(desc[0](*desc[1:]))

            else:
                for d in desc:
                    self.register(d)

    def _calculate(self, desc, cache):
        if desc.descriptor_key in cache:
            return cache[desc.descriptor_key]

        if isinstance(desc, Key):
            desc = desc.create()

        args = {name: self._calculate(dep, cache) if dep is not None else None
                for name, dep in (desc.dependencies or {}).items()}

        mol = self.molecule.get(
            explicitH=desc.explicit_hydrogens,
            gasteiger=desc.gasteiger_charges,
            kekulize=desc.kekulize,
        )
        r = desc.calculate(mol, **args)

        if desc.descriptor_key is None:
            raise ValueError('[bug] descriptor key not provided: {!r}'.format(desc))

        cache[desc.descriptor_key] = r
        return r

    def __call__(self, mol):
        cache = {}
        self.molecule = Molecule(mol)

        return (
            (desc.descriptor_name, self._calculate(desc, cache))
            for desc in self.descriptors
        )
