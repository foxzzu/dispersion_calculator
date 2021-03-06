"""
Created on 29 Mar 2017

@author: Filip Lindau
"""

import numpy as np
from scipy.interpolate import interp1d
from xml.etree import cElementTree as ElementTree
import os
import logging
import warnings

logger = logging.getLogger(__name__)
logger.setLevel(logging.CRITICAL)
#
# root = logging.getLogger()
# root.setLevel(logging.DEBUG)
warnings.filterwarnings('ignore')


class DispersionCalculator(object):
    """
    Calculation of linear dispersion through materials. The materials are specified with their
    Sellmeier coefficients and stored in a dictionary. At creation an internal set of materials
    is generated (air, fused silica (fs), bbo, sapphire, MgF2) and a materials directory (./materials)
    is scanned for XML files for additional materials.
    The XML files contain a sellmeier element and a list of tags A, B, and C with the coefficients.

    To calculate the dispersion, first generate a gaussian pulse with desired pulse duration or
    spectral width. The time span for the electric field vector and number of points are also
    specified. Then the propagation through a material is calculated with the propagate_material
    method. Additional materials can be propagated in turn by subsequent calls to this method.
    To start over call reset_propagation or generate a new gaussian pulse.

    Analysing the dispersed pulse is done through the get_xxx methods. The phase expansion requires
    a pulse spectral width of more than 3 nm to be reliable it seems.
    """
    def __init__(self, t_fwhm=50e-15, l_0=800e-9, t_span=2e-12):
        self.materials_path = "./materials"
        self.c = 299792458.0
        self.l_mat = np.linspace(200e-9, 2000e-9, 1000)
        self.phase_thr = 0.01
        self.t_span = t_span
        self.l_0 = l_0
        self.w_0 = 2 * np.pi * self.c / self.l_0
        self.N = 8192
        self.dt = self.t_span / self.N
        self.t = np.linspace(-self.t_span / 2, self.t_span / 2, self.N)
        self.w = np.fft.fftshift((2*np.pi*np.fft.fftfreq(self.N, d=self.dt)))

        self.E_t = np.array([])
        self.E_w = np.array([])
        self.E_t_out = np.array([])
        self.E_w_out = np.array([])

        self.generate_pulse(t_fwhm, l_0, t_span)

        self.materials = {}
        self.generate_materials_dict()

    def generate_pulse(self, fwhm, l_0, t_span=2e-12, n=None, duration_domain='temporal'):
        """
        Generate a gaussian pulse with fwhm parameter in time or spectrum (wavelength).
        Use SI units.
        Also generated time and frequency vectors.

        :param fwhm: Pulse width in time or spectrum
        :param l_0:  Central wavelength
        :param t_span: Time span for the generated field vector. Should be long enough to cover
                       the dispersed pulse
        :param n: Number of points in the generated field vector
        :param duration_domain: 'temporal' or 'spectral'
        :return:
        """
        self.l_0 = l_0
        self.w_0 = 2 * np.pi * self.c / self.l_0
        self.t_span = t_span
        if n is None:
            n = np.int(self.N)
        self.N = n
        self.dt = self.t_span / n
        self.t = np.linspace(-self.t_span / 2, self.t_span / 2, np.int(n))
        logger.debug("FFTShift")
        self.w = np.fft.fftshift((2 * np.pi * np.fft.fftfreq(np.int(n), d=self.dt)))
        ph = 0.0
        if duration_domain == 'temporal':
            tau = fwhm / np.sqrt(2 * np.log(2))
        else:
            tau = 0.441 * l_0**2 / (fwhm * self.c)
        logger.debug("tau {0}".format(tau))
        self.E_t = np.exp(-self.t ** 2 / tau ** 2 + ph)
        self.E_w = np.fft.fftshift(np.fft.fft(self.E_t))
        logger.debug("FFTShift done")
        self.E_t_out = self.E_t.copy()
        self.E_w_out = self.E_w.copy()
        logger.debug("copy done")

    def generate_materials_dict(self):
        """
        Generates the internal materials dict from a set of non-sellmeier materials (air, sapphire, bbo..)
        and the files in the materials directory. The dict stores scipy interp1d interpolators that are
        used to find the refractive index at specific angular frequencies later.
        :return:
        """
        w_mat = 2 * np.pi * self.c / self.l_mat
        l2_mat = (self.l_mat * 1e6) ** 2

        n_air = 1 + 0.05792105 * l2_mat / (238.0185 * l2_mat - 1) + 0.00167917 * l2_mat / (57.362 * l2_mat - 1)
        air_ip = interp1d(w_mat, n_air, bounds_error=False, fill_value=np.nan, kind="quadratic")
        self.materials['air'] = air_ip

        n_fs = np.sqrt(1 + 0.6961663 * l2_mat / (l2_mat - 0.0684043 ** 2) +
                       0.4079426 * l2_mat / (l2_mat - 0.1162414 ** 2) +
                       0.8974794 * l2_mat / (l2_mat - 9.896161 ** 2))
        fs_ip = interp1d(w_mat, n_fs, bounds_error=False, fill_value=np.nan, kind="quadratic")
        self.materials['fs'] = fs_ip

        n_mgf2 = np.sqrt(1 + 0.48755108 * l2_mat / (l2_mat - 0.04338408 ** 2) +
                         0.39875031 * l2_mat / (l2_mat - 0.09461442 ** 2) +
                         2.3120353 * l2_mat / (l2_mat - 23.793604 ** 2))
        mgf2_ip = interp1d(w_mat, n_mgf2, bounds_error=False, fill_value=np.nan, kind="quadratic")
        self.materials['mgf2'] = mgf2_ip

        n_sapphire_o = np.sqrt(1 + 1.4313493 * l2_mat / (l2_mat - 0.0726631 ** 2) +
                               0.65054713 * l2_mat / (l2_mat - 0.1193242 ** 2) +
                               5.3414021 * l2_mat / (l2_mat - 18.028251 ** 2))
        sapphire_o_ip = interp1d(w_mat, n_sapphire_o, bounds_error=False, fill_value=np.nan, kind="quadratic")
        self.materials['sapphire_o'] = sapphire_o_ip

        n_sapphire_e = np.sqrt(1 + 1.5039759 * l2_mat / (l2_mat - 0.0740288 ** 2) +
                               0.55069141 * l2_mat / (l2_mat - 0.1216529 ** 2) +
                               6.5927379 * l2_mat / (l2_mat - 20.072248 ** 2))
        sapphire_e_ip = interp1d(w_mat, n_sapphire_e, bounds_error=False, fill_value=np.nan, kind="quadratic")
        self.materials['sapphire_e'] = sapphire_e_ip

        n_bbo_o = np.sqrt(2.7405 + 0.0184 / (l2_mat - 0.0179) - 0.0155 * l2_mat)
        bbo_o_ip = interp1d(w_mat, n_bbo_o, bounds_error=False, fill_value=np.nan, kind="quadratic")
        self.materials['bbo_o'] = bbo_o_ip

        n_bbo_e = np.sqrt(2.3730 + 0.0128 / (l2_mat - 0.0156) - 0.0044 * l2_mat)
        bbo_e_ip = interp1d(w_mat, n_bbo_e, bounds_error=False, fill_value=np.nan, kind="quadratic")
        self.materials['bbo_e'] = bbo_e_ip

        materials_files = os.listdir(self.materials_path)
        logger.info("Found {0:d}".format(materials_files.__len__()))
        for mat_file in materials_files:
            logger.info(mat_file)
            self.read_material(''.join((self.materials_path, '/', mat_file)))

    def add_material(self, name, b_coeff, c_coeff):
        """
        Adds a material to the internal materials dict. The material is specified with it's sellmeier
        coefficients: n = sqrt(1 + sum(B * l**2 / (l**2 - C))

        The wavelengths are in um as customary in Sellmeier equations.

        The dict stores scipy interp1d interpolators that are used to find the refractive index at
        specific angular frequencies later.

        :param name: String containing the name of the material (used as key in the dict)
        :param b_coeff: Vector of B-coefficients for the Sellmeier equation (for lambda in um)
        :param c_coeff: Vector of C-coefficients for the Sellmeier equation (for lambda in um)
        :return:
        """
        """

        :return:
        """
        l_mat = np.linspace(200e-9, 2000e-9, 5000)
        w_mat = 2 * np.pi * self.c / l_mat
        l2_mat = (l_mat * 1e6) ** 2
        n_tmp = 0.0
        for ind, b in enumerate(b_coeff):
            n_tmp += b*l2_mat / (l2_mat - c_coeff[ind])
        n = np.sqrt(1 + n_tmp)
        n_ip = interp1d(w_mat, n, bounds_error=False, fill_value=np.nan, kind="quadratic")
        self.materials[name] = n_ip

    def read_material(self, filename):
        """
        Read an xml file and extract the sellmeier coeffients from it. The file should have
        elements called sellmeier with tags called A, B, and C. The refractive index is then
        calculated as:
        n = sqrt(1 + sum(A + B * l**2 / (l**2 - C))

        The wavelengths are in um as customary in Sellmeier equations.

        The A coefficients were added to allow certain types of materials in the refractiveindex.info
        database.

        :param filename: String containing the filename
        :return:
        """
        l_mat = np.linspace(200e-9, 2000e-9, 5000)
        w_mat = 2 * np.pi * self.c / l_mat
        l2_mat = (l_mat * 1e6) ** 2
        n_tmp = 0.0

        e = ElementTree.parse(filename)
        mat = e.getroot()
        name = mat.get('name')
        sm = mat.findall('sellmeier')
        for s in sm:
            at = s.find('A')
            if at is not None:
                a = np.double(at.text)
            else:
                a = 0.0
            bt = s.find('B')
            if bt is not None:
                b = np.double(bt.text)
            else:
                b = 0.0
            ct = s.find('C')
            if ct is not None:
                c = np.double(ct.text)
            else:
                c = 0.0
            n_tmp += a + b*l2_mat / (l2_mat - c)
        n = np.sqrt(1 + n_tmp)
        n_ip = interp1d(w_mat, n, bounds_error=False, fill_value=np.nan)
        self.materials[name] = n_ip

    def propagate_material(self, name, thickness):
        """
        Propagate the current pulse through a thickness of material. The propagation is performed
        in the fourier domain by spectral filtering. The pulse is then inverse transformed to
        the time domain.

        :param name: String containing the name of the material (to match a key in the materials dict)
        :param thickness: Thickness of the material (SI units)
        :return:
        """
        logger.debug("Entering propagate_material {0}, {1}".format(name, thickness))
        try:
            k_w = (self.w + self.w_0) * self.materials[name](self.w + self.w_0) / self.c
        except KeyError:
            return
        H_w = np.exp(-1j * k_w * thickness)
        H_w[np.isnan(H_w)] = 0
        self.E_w_out = H_w * self.E_w_out.copy()
        self.E_t_out = np.fft.ifft(np.fft.fftshift(self.E_w_out))

    def reset_propagation(self):
        """
        Resets the propagation to it's initial gaussian pulse.

        :return:
        """
        logger.debug("Entering reset_propagation")
        self.E_w_out = self.E_w.copy()
        self.E_t_out = self.E_t.copy()

    def get_temporal_intensity(self, norm=True):
        logger.debug("Entering get_temporal_intensity")
        if self.E_t_out.size != 0:
            # Center peak in time
            ind = np.argmax(np.abs(self.E_t_out))
            shift = (self.E_t_out.shape[0] / 2 - ind).astype(np.int)
            I_t = np.abs(np.roll(self.E_t_out, shift))**2
            if norm is True:
                I_t /= I_t.max()
        else:
            I_t = None
        return I_t

    def get_temporal_phase(self, linear_comp=False):
        logger.debug("Entering get_temporal_phase")
        eps = self.phase_thr

        if self.E_t_out.size != 0:
            # Center peak in time
            ind = np.argmax(abs(self.E_t_out))
            shift = self.E_t_out.shape[0] / 2 - ind
            E_t = np.roll(self.E_t_out, shift)

            # Unravelling 2*pi phase jumps
            ph0_ind = np.int(E_t.shape[0] / 2)  # Center index
            ph = np.angle(E_t)
            ph_diff = np.diff(ph)
            # We need to sample often enough that the difference in phase is less than 5 rad
            # A larger jump is taken as a 2*pi phase jump
            ph_ind = np.where(np.abs(ph_diff) > 5.0)
            # Loop through the 2*pi phase jumps
            for ind in ph_ind[0]:
                if ph_diff[ind] < 0:
                    ph[ind + 1:] += 2 * np.pi
                else:
                    ph[ind + 1:] -= 2 * np.pi

            # Find relevant portion of the pulse (intensity above a threshold value)
            ph0 = ph[ph0_ind]
            E_t_mag = np.abs(E_t)
            low_ind = np.where(E_t_mag < eps)
            ph[low_ind] = np.nan

            # Here we could go through contiguous regions and make the phase connect at the edges...

            # Linear compensation is we have a frequency shift (remove 1st order phase)
            if linear_comp is True:
                idx = np.isfinite(ph)
                x = np.arange(E_t.shape[0])
                ph_poly = np.polyfit(x[idx], ph[idx], 1)
                ph_out = ph - np.polyval(ph_poly, x)
            else:
                ph_out = ph - ph0
        else:
            ph_out = None
        return ph_out

    def get_spectral_intensity(self, norm=True):
        logger.debug("Entering get_spectral_intensity")
        if self.E_w_out.size != 0:
            # Center peak in time
            ind = np.argmax(abs(self.E_w_out))
            shift = (self.E_w_out.shape[0] / 2 - ind).astype(np.int)
            I_w = np.abs(np.roll(self.E_w_out, shift))**2
            if norm is True:
                I_w /= I_w.max()
        else:
            I_w = None
        return I_w

    def get_spectral_phase(self, linear_comp=True):
        """
        Retrieve the spectral phase of the propagated E-field. The phase is zero at the peak field and NaN
        where the field magnitude is lower than the threshold phase_thr (class variable). Use get_w for the
        corresponding angular frequency vector.

        :param linear_comp: If true, the linear part of the phase (i.e. time shift) if removed
        :return: Spectral phase vector.
        """
        logger.debug("Entering get_spectral_phase")
        eps = self.phase_thr    # Threshold for intensity where we have signal

        # Check if there is a reconstructed field:
        if self.E_t_out is not None:

            # Center peak in time
            ind = np.argmax(abs(self.E_t_out))
            shift = - ind
            E_t = np.roll(self.E_t_out, shift)
            Ew = np.fft.fftshift(np.fft.fft(E_t))

            # Normalize
            Ew /= abs(Ew).max()

            # Unravelling 2*pi phase jumps
            ph0_ind = np.argmax(abs(Ew))
            ph = np.angle(Ew)
            ph_diff = np.diff(ph)
            # We need to sample often enough that the difference in phase is less than 5 rad
            # A larger jump is taken as a 2*pi phase jump
            ph_ind = np.where(np.abs(ph_diff) > 5.0)
            # Loop through the 2*pi phase jumps
            for ind in ph_ind[0]:
                if ph_diff[ind] < 0:
                    ph[ind + 1:] += 2 * np.pi
                else:
                    ph[ind + 1:] -= 2 * np.pi

            # Find relevant portion of the pulse (intensity above a threshold value)
            Ew_mag = np.abs(Ew)
            low_ind = np.where(Ew_mag < eps)
            ph[low_ind] = np.nan

            # Here we could go through contiguous regions and make the phase connect at the edges...

            # Linear compensation is we have a frequency shift (remove 1st order phase)
            if linear_comp is True:
                idx = np.isfinite(ph)
                x = np.arange(Ew.shape[0])
                ph_poly = np.polyfit(x[idx], ph[idx], 1)
                ph_out = ph - np.polyval(ph_poly, x)
            else:
                ph_out = ph
            ph_out -= ph_out[ph0_ind]
        else:
            ph_out = None
        return ph_out

    def get_spectral_phase_expansion(self, orders=4, prefix=1e12):
        """
        Calculate a polynomial fit to the retrieved phase curve as function of angular frequency (spectral phase)
        :param orders: Number of orders to include in the fit
        :param prefix: Factor that the angular frequency is scaled with before the fit (1e12 => Trad)
        :return: Polynomial coefficients, highest order first
        """
        if self.E_t_out is not None:
            # w = self.w
            # w = self.w + self.w_0
            w = self.get_w()
            ph = self.get_spectral_phase()
            ph_ind = np.isfinite(ph)
            ph_good = ph[ph_ind]
            w_good = w[ph_ind] / prefix
            ph_poly = np.polyfit(w_good, ph_good, orders)
        else:
            ph_poly = None
        return ph_poly

    def get_pulse_duration(self, domain='temporal'):
        """
        Calculate pulse parameters such as intensity FWHM.
        :param domain: 'temporal' for time domain parameters,
                     'spectral' for frequency domain parameters
        :return:
        trace_fwhm: full width at half maximum of the intensity trace (E-field squared)
        delta_ph: phase difference (max-min) of the phase trace
        """
        logger.debug("Entering get_pulse_duration")
        if domain == 'temporal':
            I = self.get_temporal_intensity(True)
            x = self.get_t()
        else:
            I = self.get_spectral_intensity(True)
            x = self.get_w()

        # Calculate FWHM
        x_ind = np.where(np.diff(np.sign(I - 0.5)))[0]
        if x_ind.shape[0] > 1:
            trace_fwhm = x[x_ind[-1]] - x[x_ind[0]]
        else:
            trace_fwhm = np.nan
        logger.debug("t_fwhm: {0}".format(trace_fwhm))
        return trace_fwhm

    def get_t(self):
        return self.t

    def get_w(self):
        w = self.w + self.w_0
        return w


if __name__ == "__main__":
    dc = DispersionCalculator(50e-15, 800e-9, 2e-12)
    dc.propagate_material("bk7", 10e-3)
