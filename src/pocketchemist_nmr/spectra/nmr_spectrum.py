"""
NMR Spectra in different formats
"""
import abc
import typing as t
from pathlib import Path

from pocketchemist.processors import FFTType

from .constants import DomainType

__all__ = ('NMRSpectrum',)


# Abstract base class implementation
class NMRSpectrum(abc.ABC):
    """An NMR spectrum base class.

    .. note::
          The base class handles the generic processing methodology.
          Subclasses should override methods that are specific to their
          implementation--specifically when interating with the self.meta
          dict, which is implementation specific.
    """

    #: metadata on the spectrum
    meta: dict

    #: The data for the spectrum, either an array or an iterator
    data: 'torch.Tensor'

    #: If specified, this is the iterator do generate sub-spectra from
    #: multiple files
    iterator = None

    #: If True, then all of the subspectra for the iterator have been
    #: accessed (i.e. a StopIteration was raised)
    iterator_done: t.Optional[bool] = None

    #: The filepath for the file corresponding to the spectrum
    in_filepath: 'pathlib.Path'

    #: The (optional) filepath to write the processed spectrum
    out_filepath: t.Optional['pathlib.Path']

    #: The default attributes that are set to None when reset
    reset_attrs = ('data', 'in_filepath', 'out_filepath')

    def __init__(self, in_filepath, out_filepath=None):
        self.reset()
        self.in_filepath = Path(in_filepath)
        self.out_filepath = (Path(out_filepath)
                             if out_filepath is not None else None)

        # Load the spectrum
        self.load()

    def __iter__(self):
        """Return an iterator of the spectrum, if the spectrum is in iterator
        mode.
        """
        return self if self.is_iterator else None

    def __next__(self):
        """Advance the iterator of the spectrum, if the spectrum is in
        iterator mode. """
        raise NotImplementedError

    # Basic accessor/mutator methods

    @property
    @abc.abstractmethod
    def ndims(self) -> int:
        """The number of dimensions in the spectrum"""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def order(self) -> t.Tuple[int, ...]:
        """The order of the dimensions for the data.

        Valid dimensions start with 1 and end with the number of dimensions
        (self.ndims).

        Returns
        -------
        order
            The ordering of the dimensions for the :attr:`data` dataset.
            - The first dimension corresponds to the rows of the dataset
              (axis=1 for numpy)
            - The second dimension corresponds to the columns of the dataset
              (axis=0 for numpy)
            - The third and higher dimensions corresponds to additional
              dimensions, which may be represented by an iterator
        """
        raise NotImplementedError

    @order.setter
    @abc.abstractmethod
    def order(self, new_order: t.Tuple[int, ...]):
        """Change the order of the dimensions for the data.

        Valid dimensions start with 1 and end with the number of dimensions
        (self.ndims).

        Parameters
        ----------
        new_order
            The new order of the dataset. This function is typically invoked
            for transpose operations.
        """
        raise NotImplementedError

    def domain_type(self,
                    dim: int = None,
                    value: t.Optional[DomainType] = None) -> DomainType:
        """The data domain type for the given dimension

        Parameters
        ----------
        dim
            The dimension (1-4) to evaluate the domain type. By default,
            the current dimension is used.
        value
            If specified, set the domain type to this value

        Returns
        -------
        domain_type
            The current value of the domain type setting.
        """
        raise NotImplementedError

    # I/O methods

    @abc.abstractmethod
    def load(self, in_filepath: t.Optional['pathlib.Path'] = None):
        """Load the spectrum

        Parameters
        ----------
        in_filepath
            The (optional) filepath to use for loading the spectrum, instead
            of self.in_filepath.
        """
        # Setup arguments
        in_filepath = (Path(in_filepath) if in_filepath is not None else
                       self.in_filepath)

        # Reset attrs, excluding in_filepath and out_filepath
        reset_attrs = tuple(attr for attr in self.reset_attrs
                            if attr not in ('in_filepath', 'out_filepath'))
        self.reset(attrs=reset_attrs)

    @abc.abstractmethod
    def save(self,
             out_filepath: t.Optional['pathlib.Path'] = None,
             format: str = None,
             overwrite: bool = True):
        """Save the spectrum to the specified filepath

        Parameters
        ----------
        out_filepath
            The filepath for the file(s) to save the spectrum.
        format
            The format of the spectrum to write. By default, this is nmrpipe.
        overwrite
            If True (default), overwrite existing files.
        """
        pass

    def reset(self, attrs: t.Optional[t.Tuple[str, ...]] = None):
        """Reset the data and parameters for the spectrum.

        Parameters
        ----------
        attrs
            A listing of attributes to clear.
        """
        if hasattr(self, 'meta') and isinstance(self.meta, dict):
            self.meta.clear()
        else:
            self.meta = dict()

        # Rest the attributes
        attrs = attrs if attrs is not None else self.reset_attrs
        for attr in attrs:
            setattr(self, attr, None)

    def ft(self,
           ft_func: t.Callable,
           auto: bool = False,
           real: bool = False,
           inv: bool = False,
           alt: bool = False,
           neg: bool = False,
           bruk: bool = False,
           data: t.Optional['numpy.ndarray'] = None,
           **kwargs):
        """Perform a Fourier Transform

        This method is designed to be used on instances and as a class method.

        Parameters
        ----------
        ft_func
            The Fourier Transform wrapper functions to use.
        auto
            Try to determine the FT flags automatically
        real
            Apply a real Fourier transform (.FFTType.RFFT)
        inv
            Apply an inverse Fourier transform (.FFTType.IFFT)
        alt
            Alternate the sign of points before Fourier transform
        neg
            Negate imaginary component of complex numbers before Fourier
            transform
        bruk
            Process Redfield sequential data, which is alt and real.
        meta
            Metadata on the spectrum
        data
            The data to Fourier Transform

        Returns
        -------
        kwargs
            The kwargs dict with the 'data' entry populated with the Fourier
            Transformed dataset.

        See Also
        --------
        - nmrglue.process.proc_base
        """
        # Setup the arguments
        data = data if data is not None else self.data

        # Setup the flags
        if auto:
            # The auto flag should be set to False when this method is called
            # by children methods. Children methods are responsible for
            # determining how to apply and 'auto' processing
            raise NotImplementedError

        if bruk:
            # Adjust flags for Redfield sequential data
            real = True
            alt = True
        if real:
            # Remove the imaginary component for real transformation
            data.imag = 0.0
        if inv:
            # Set the FFT function type to inverse Fourier transformation
            ft_func.fft_type = FFTType.IFFT
        if alt and not inv:
            # Alternate the sign of points
            data[..., 1::2] = data[..., 1::2] * -1.
        if neg:
            # Negate (multiple by -1) the imaginary component
            data.imag *= -1.0

        # Perform the FFT then a frequency shift
        self.data = ft_func(data=data)

        # Post process the data
        if inv and alt:
            data[..., 1::2] = data[..., 1::2] * -1

        # Prepare the return value
        kwargs['data'] = data
        return kwargs
