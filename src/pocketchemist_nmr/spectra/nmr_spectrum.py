"""
NMR Spectra in different formats
"""
import abc
import typing as t
from pathlib import Path

import torch

from .constants import DomainType, DataType, DataLayout
from .meta import NMRMetaDict
from .utils import (split_block_to_complex, combine_block_from_complex,
                    interleave_single_to_block, interleave_block_to_single)

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

    #: metadata on the spectrum.
    #: All methods should maintain the correct integrity of the metadata
    meta: NMRMetaDict

    #: The data for the spectrum, either an array or an iterator
    data: 'torch.Tensor'

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

    # Basic accessor/mutator methods

    @property
    @abc.abstractmethod
    def ndims(self) -> int:
        """The number of dimensions in the spectrum"""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def domain_type(self) -> t.Tuple[DomainType, ...]:
        """The data domain type (freq, time) for all available dimensions, as
        ordered in the data.

        Returns
        -------
        domain_type
            The current value of the domain type setting.
        """
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def data_type(self) -> t.Tuple[DataType, ...]:
        """The type data (real, imag, complex) of all available dimensions, as
        ordered in the data."""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def sw(self) -> t.Tuple[int, ...]:
        """Spectral widths (in Hz) of all available dimensions, as ordered in
        the data."""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def label(self) -> t.Tuple[str, ...]:
        """The labels for all dimensions, as ordered in the data."""
        raise NotImplementedError

    @abc.abstractmethod
    def data_layout(self, data_type: DataType, dim: int) -> DataLayout:
        """Give the expected data layout for the given data type and dimension.

        Parameters
        ----------
        data_type
            The data type (Complex, Real, Imag) for which the data layout
            should be investigated.
        dim
            The dimension for the data for which the data layout should be
            investigated. The dimension starts at 0 (outer loop) and ends at
            self.ndims - 1 (inner loop)

        Returns
        -------
        data_layout
            The data layout for the given data type and dimension
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
        if hasattr(self, 'meta') and hasattr(self.meta, 'clear'):
            self.meta.clear()
        else:
            # Create a new meta dict based on the annotation
            meta_cls = t.get_type_hints(self)['meta']
            self.meta = meta_cls()

        # Rest the attributes
        attrs = attrs if attrs is not None else self.reset_attrs
        for attr in attrs:
            setattr(self, attr, None)

    # Manipulator methods
    def transpose(self, dim0, dim1, interleave_complex=True):
        """Transpose two axes (dim0 <-> dim1)

        Parameters
        ----------
        dim0
            The first dimension to transpose, starting from 0 to self.ndims - 1
        dim1
            The second dimension to transpose, starting from 0 to self.ndims - 1
        interleave_complex
            If True (default), reorganize complex data by interleaving/
            deinterleaving according to the self.data_layout.
        """
        # Only works if there is more than 1 dimension
        assert self.ndims > 1, (
            "Can only permute multiple dimensions")

        # Sort the order of the dimensions
        dim0, dim1 = min(dim0, dim1), max(dim0, dim1)

        # Get the data_type and data_layout for each dimension
        data_type = self.data_type
        data_type0, data_type1 = data_type[dim0], data_type[dim1]

        # Determine the data_layout before and after transpose
        before_layout0, before_layout1 = (self.data_layout(data_type0, dim0),
                                          self.data_layout(data_type1, dim1))
        after_layout0, after_layout1 = (self.data_layout(data_type1, dim0),
                                        self.data_layout(data_type0, dim1))

        # The interleave in the last dimension is handled as a special case,
        # since it may have a different interleave than the other dimensions
        # (see NMRPipeSpectrum)
        if interleave_complex and self.ndims - 1 == dim1:
            if data_type1 is DataType.COMPLEX:
                # Currently only implemented for a block layout in the last
                # dimension
                assert before_layout1 is DataLayout.BLOCK_INTERLEAVE

                # Unpack complex values in the last dimension
                self.data = combine_block_from_complex(self.data)

                # Change the layout in the last dimension, if the layout to
                # the new dimension is different
                if after_layout1 is DataLayout.SINGLE_INTERLEAVE:
                    self.data = interleave_block_to_single(self.data)

        # Conduct the transpose
        self.data = torch.transpose(self.data, dim0, dim1)

        # Determine if the interleave has to be change in the last dimension
        if interleave_complex and self.ndims - 1 == dim1:
            if data_type0 is DataType.COMPLEX:
                # Convert to block interleave before converting to complex
                if before_layout0 is DataLayout.SINGLE_INTERLEAVE:
                    self.data = interleave_single_to_block(self.data)

                # Split to form complex numbers
                self.data = split_block_to_complex(self.data)

    def phase(self, p0: float, p1: float, discard_imaginaries: bool = True):
        """Apply phase correction to the last dimension

        Parameters
        ----------
        p0
            The zero-order phase correction in degrees
        p1
            The first-order phase correction in degrees / Hz
        discard_imaginaries
            Only keep the real component of complex numbers after phase
            correction and discard the imaginary component
        """
        # Get the spectra width and data length for the last dimension
        sw = self.sw[-1]
        npts = self.data.size()[-1]
        freqs = torch.linspace(-sw / 2., sw / 2., npts )
        phase = p0 + p1*freqs
        self.data *= torch.exp(phase * 1.j)
        if discard_imaginaries:
            self.data = self.data.real

    def ft(self,
           auto: bool = False,
           real: bool = False,
           inv: bool = False,
           alt: bool = False,
           neg: bool = False,
           bruk: bool = False,
           **kwargs):
        """Perform a Fourier Transform to the last dimension

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
        fft_func = torch.fft.fft

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
            self.data.imag = 0.0
        if inv:
            # Set the FFT function type to inverse Fourier transformation
            fft_func = torch.fft.ifft
        if alt and not inv:
            # Alternate the sign of points
            self.data[..., 1::2] = self.data[..., 1::2] * -1.
        if neg:
            # Negate (multiple by -1) the imaginary component
            self.data.imag *= -1.0

        # Perform the FFT then a frequency shift
        self.data = fft_func(self.data)

        # Post process the data
        if inv and alt:
            self.data[..., 1::2] = self.data[..., 1::2] * -1

        # Prepare the return value
        return kwargs
