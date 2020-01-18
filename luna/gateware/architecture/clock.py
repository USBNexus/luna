#
# This file is part of LUNA.
#
""" Clock domain generation logic for LUNA. """

from abc import ABCMeta, abstractmethod
from nmigen import Signal, Module, ClockDomain, ClockSignal, Elaboratable, Instance

from ..util import stretch_strobe_signal

class LunaDomainGenerator(Elaboratable, metaclass=ABCMeta):
    """ Helper that generates the clock domains used in a LUNA board.

    Note that this module should create three in-phase clocks; so these domains
    should not require explicit boundary crossings.
    
    I/O port:
        O: clk_fast -- The clock signal for our fast clock domain.
        O: clk_sync -- The clock signal used for our sync clock domain.
        O: clk_ulpi -- The clock signal used for our ulpi domain.
    """

    def __init__(self, *, clock_signal_name=None):
        """
        Parameters:
            clock_signal_name = The clock signal name to use; or None to use the platform's default clock.
        """

        self.clock_name = clock_signal_name

        #
        # I/O port
        #
        self.clk_fast     = Signal()
        self.clk_sync     = Signal()
        self.clk_ulpi     = Signal()
        self.clk_fast_out = Signal()


    @abstractmethod
    def generate_fast_clock(self, m, platform):
        """ Method that returns our platform's fast clock; used for e.g. RAM interfacing. """


    @abstractmethod
    def generate_fast_out_clock(self, m, platform):
        """ Method that returns our platform's fast clock; phase offset to accommodate any delays. """


    @abstractmethod
    def generate_sync_clock(self, m, platform):
        """ Method that returns our platform's primary synchronous clock. """


    @abstractmethod
    def generate_ulpi_clock(self, m, platform):
        """ Method that generates a 60MHz clock used for ULPI interfacing. """


    def create_submodules(self, m, platform):
        """ Method hook for creating any necessary submodules before generating clock. """
        pass


    def elaborate(self, platform):
        m = Module()

        # Create our clock domains.
        m.domains.fast = ClockDomain()
        m.domains.sync = ClockDomain()
        m.domains.ulpi = ClockDomain()

        # Create a clock domain that shifts on the falling edges of the fast clock.
        m.domains.fast_out = ClockDomain()

        # Call the hook that will create any submodules necessary for all clocks.
        self.create_submodules(m, platform)

        # Generate and connect up our clocks.
        m.d.comb += [
            self.clk_ulpi                  .eq(self.generate_ulpi_clock(m, platform)),
            self.clk_sync                  .eq(self.generate_sync_clock(m, platform)),
            self.clk_fast                  .eq(self.generate_fast_clock(m, platform)),
            self.clk_fast_out              .eq(self.generate_fast_out_clock(m, platform)),

            ClockSignal(domain="fast")     .eq(self.clk_fast),
            ClockSignal(domain="fast_out") .eq(self.clk_fast_out),
            ClockSignal(domain="sync")     .eq(self.clk_sync),
            ClockSignal(domain="ulpi")     .eq(self.clk_ulpi),
        ]

        return m


class LunaECP5DomainGenerator(LunaDomainGenerator):
    """ ECP5 clock domain generator for LUNA. Assumes a 60MHz input clock. """

    # Quick configuration selection
    DEFAULT_CLOCK_FREQUENCIES_MHZ = {
        "fast": 240,
        "sync": 120,
        "ulpi": 60
    }

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        """
        Parameters:
            clock_frequencies -- A dictionary mapping 'fast', 'sync', and 'ulpi' to the clock
                                 frequencies for those domains, in MHz. Valid choices for each
                                 domain are 60, 120, and 240. If not provided, fast will be
                                 assumed to be 240, sync will assumed to be 120, and ulpi will
                                 be assumed to be a standard 60.
        """
        super().__init__(clock_signal_name=clock_signal_name)

        # If we don't have a dictionary of clock frequencies, use the default.
        if clock_frequencies is None:
            self.clock_frequencies = self.DEFAULT_CLOCK_FREQUENCIES_MHZ
        else:
            self.clock_frequencies = clock_frequencies


    def create_submodules(self, m, platform):

        self._pll_lock   = Signal()

        # Use the provided clock name for our input; or the default clock
        # if no name was provided.
        clock_name = self.clock_name if self.clock_name else platform.default_clk

        # Create absolute-frequency copies of our PLL outputs.
        # We'll use the generate_ methods below to select which domains
        # apply to which components.
        self._clk_240MHz = Signal()
        self._clk_120MHz = Signal()
        self._clk_60MHz  = Signal()
        self._clock_options = {
            60:  self._clk_60MHz,
            120: self._clk_120MHz,
            240: self._clk_240MHz
        }

        # Instantiate the ECP5 PLL.
        # These constants generated by Clarity Designer; which will
        # ideally be replaced by an open-source component. 
        # (see https://github.com/SymbiFlow/prjtrellis/issues/34.)
        m.submodules.pll = Instance("EHXPLLL",

                # Clock in.
                i_CLKI=platform.request(clock_name),

                # Generated clock outputs.
                o_CLKOP=self._clk_240MHz,
                o_CLKOS=self._clk_120MHz,
                o_CLKOS2=self._clk_60MHz,

                # Status.
                o_LOCK=self._pll_lock,

                # PLL parameters...
                p_PLLRST_ENA="DISABLED",
                p_INTFB_WAKE="DISABLED",
                p_STDBY_ENABLE="DISABLED",
                p_DPHASE_SOURCE="DISABLED",
                p_CLKOS3_FPHASE=0,
                p_CLKOS3_CPHASE=0,
                p_CLKOS2_FPHASE=0,
                p_CLKOS2_CPHASE=7,
                p_CLKOS_FPHASE=0,
                p_CLKOS_CPHASE=3,
                p_CLKOP_FPHASE=0,
                p_CLKOP_CPHASE=1,
                p_PLL_LOCK_MODE=0,
                p_CLKOS_TRIM_DELAY="0",
                p_CLKOS_TRIM_POL="FALLING",
                p_CLKOP_TRIM_DELAY="0",
                p_CLKOP_TRIM_POL="FALLING",
                p_OUTDIVIDER_MUXD="DIVD",
                p_CLKOS3_ENABLE="DISABLED",
                p_OUTDIVIDER_MUXC="DIVC",
                p_CLKOS2_ENABLE="ENABLED",
                p_OUTDIVIDER_MUXB="DIVB",
                p_CLKOS_ENABLE="ENABLED",
                p_OUTDIVIDER_MUXA="DIVA",
                p_CLKOP_ENABLE="ENABLED",
                p_CLKOS3_DIV=1,
                p_CLKOS2_DIV=8,
                p_CLKOS_DIV=4,
                p_CLKOP_DIV=2,
                p_CLKFB_DIV=4,
                p_CLKI_DIV=1,
                p_FEEDBK_PATH="CLKOP",

                # Internal feedback.
                i_CLKFB=self._clk_240MHz,

                # Control signals.
                i_RST=0,
                i_PHASESEL0=0,
                i_PHASESEL1=0,
                i_PHASEDIR=0,
                i_PHASESTEP=0,
                i_PHASELOADREG=0,
                i_STDBY=0,
                i_PLLWAKESYNC=0,

                # Output Enables.
                i_ENCLKOP=0,
                i_ENCLKOS=0,
                i_ENCLKOS2=0,
                i_ENCLKOS3=0,

                # Synthesis attributes.
                a_FREQUENCY_PIN_CLKI="60.000000",
                a_FREQUENCY_PIN_CLKOS2="60.000000",
                a_FREQUENCY_PIN_CLKOS="120.000000",
                a_FREQUENCY_PIN_CLKOP="240.000000",
                a_ICP_CURRENT="9",
                a_LPF_RESISTOR="8"
        )


    def generate_ulpi_clock(self, m, platform):
        return self._clock_options[self.clock_frequencies['ulpi']]

    def generate_sync_clock(self, m, platform):
        return self._clock_options[self.clock_frequencies['sync']]

    def generate_fast_clock(self, m, platform):
        return self._clock_options[self.clock_frequencies['fast']]

    def generate_fast_out_clock(self, m, platform):
        frequency = self.clock_frequencies['fast']

        # Accommodate varying delays in our signals.
        # If we're above 120MHz for our signals, don't try to center
        # our clocks around the edges.
        if frequency > 120:
            return self._clock_options[frequency]
        else:
            return ~self._clock_options[frequency]


    def stretch_sync_strobe_to_ulpi(self, m, strobe, output=None, allow_delay=False):
        """
        Helper that stretches a strobe from the `sync` domain to communicate with the `ulpi` domain. 
        Works for any chosen frequency in which f(ulpi) < f(sync).
        """
        to_cycles = self.clock_frequencies['sync'] // self.clock_frequencies['ulpi']
        return stretch_strobe_signal(m, strobe, output=output, to_cycles=to_cycles, allow_delay=allow_delay)