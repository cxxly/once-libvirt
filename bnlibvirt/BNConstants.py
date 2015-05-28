#
# Shutdown codes and reasons.
#

DOMAIN_POWEROFF = 0 
DOMAIN_REBOOT   = 1
DOMAIN_SUSPEND  = 2
DOMAIN_CRASH    = 3
DOMAIN_HALT     = 4

DOMAIN_SHUTDOWN_REASONS = {
    DOMAIN_POWEROFF: "poweroff",
    DOMAIN_REBOOT  : "reboot",
    DOMAIN_SUSPEND : "suspend",
    DOMAIN_CRASH   : "crash",
    DOMAIN_HALT    : "halt"
}
REVERSE_DOMAIN_SHUTDOWN_REASONS = \
    dict([(y, x) for x, y in DOMAIN_SHUTDOWN_REASONS.items()])

HVM_PARAM_CALLBACK_IRQ = 0
HVM_PARAM_STORE_PFN    = 1
HVM_PARAM_STORE_EVTCHN = 2
HVM_PARAM_PAE_ENABLED  = 4
HVM_PARAM_IOREQ_PFN    = 5
HVM_PARAM_BUFIOREQ_PFN = 6
HVM_PARAM_NVRAM_FD     = 7 # ia64
HVM_PARAM_VHPT_SIZE    = 8 # ia64
HVM_PARAM_BUFPIOREQ_PFN = 9 # ia64
HVM_PARAM_VIRIDIAN     = 9 # x86
HVM_PARAM_TIMER_MODE   = 10
HVM_PARAM_HPET_ENABLED = 11
HVM_PARAM_ACPI_S_STATE = 14
HVM_PARAM_VPT_ALIGN    = 16
HVM_PARAM_CONSOLE_PFN  = 17
HVM_PARAM_NESTEDHVM    = 24 # x86

restart_modes = [
    "restart",
    "destroy",
    "preserve",
    "rename-restart",
    "coredump-destroy",
    "coredump-restart"
    ]

DOM_STATES = [
    'halted',
    'paused',
    'running',
    'suspended',
    'shutdown',
    'crashed',
    'unknown',
]

DOM_STATE_HALTED = 0
DOM_STATE_PAUSED = 1
DOM_STATE_RUNNING = 2
DOM_STATE_SUSPENDED = 3
DOM_STATE_SHUTDOWN = 4
DOM_STATE_CRASHED = 5
DOM_STATE_UNKNOWN = 6