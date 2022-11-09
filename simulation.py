import logging
import pdb
from progress.bar import Bar  # https://pypi.python.org/pypi/progress
import sys # for command-line args

# now call the parser to parse the file
from parser import Parser
from rng_mt19937 import *
from parameters import *

from event_list import EventList
from sponge import Sponge
from symbiont import *

################################################################################
class Placement(Enum):
    ''' enumeration to characterize initial symbiont placement '''
    RANDOMIZE  = 0
    HORIZONTAL = 1
    VERTICAL   = 2

################################################################################
class Simulation:
    ''' class to implement initialization of the agent-based simulation model
        and containing the event-driven loop driving the simulation
    '''

    # class-level variables
    _current_time                 : float               = None
    _show_progress                : bool                = None
    _progress_bar                 : Bar                 = None
    _input_cvs_fname              : str                 = None
    _current_time                 : float               = None
    _current_day                  : int                 = None
    _end_time                     : float               = None
    _num_symbionts                : int                 = None
    _num_symbionts_per_clade      : list[int]           = None
    _prev_num_symbionts           : int                 = None
    _prev_num_symbionts_per_clade : list[int]           = None
    _population_file              : '_io.TextIOWrapper' = None
    _num_rows                     : int                 = None
    _num_cols                     : int                 = None
    _sponge                       : Sponge              = None
    _event_list                   : EventList           = None

    ########################
    @classmethod
    def usage(cls) -> None:
        ''' method to print usage and exit '''
        print(f"python {sys.argv[0]} [input CSV filename] [show progress (default: True)]")
        sys.exit(1)

    ##################################
    @classmethod
    def writePopulation(cls, time: float) -> None:
        ''' write the population time series as the simulation executes 
        Parameters:
            time: floating-point time that population is being written
        '''
        # first, check to see if days were possibly skipped:
        if int(time) > cls._current_day:
            while cls._current_day < int(time):
                if cls._show_progress: cls._progress_bar.next()
                cls._population_file.write(f"{cls._current_day}\t{cls._prev_num_symbionts}")
                for i in range(Parameters.NUM_CLADES):
                    cls._population_file.write(f"\t{cls._prev_num_symbionts_per_clade[i]}")
                cls._population_file.write('\n')
                cls._current_day += 1

        # then move to the current day
        if int(time) == cls._current_day:
            if cls._show_progress: cls._progress_bar.next()
            cls._population_file.write(f"{cls._current_day}\t{cls._num_symbionts}")
            for i in range(Parameters.NUM_CLADES):
                cls._population_file.write(f"\t{cls._num_symbionts_per_clade[i]}")
            cls._population_file.write('\n')
            cls._current_day += 1
            cls._prev_num_symbionts = cls._num_symbionts
            for i in range(Parameters.NUM_CLADES):
                cls._prev_num_symbionts_per_clade[i] = cls._num_symbionts_per_clade[i]

    ################################################################################
    @classmethod
    def run(cls) -> None:
        ''' class-level method to implement the main simulation code / loop '''

        try:    cls._input_csv_fname = sys.argv[1]
        except: cls.usage()
    
        try:    cls._show_progress = eval(sys.argv[2])  # eval("False") works...
        except: cls._show_progress = True
    
        ################################################################
        # parse the simulation parameters provided in the input CSV file
        Parser.parseCSVInput(cls._input_csv_fname)
        Symbiont.computeCumulativeCladeProportions()
        ################################################################

        RNG.initializeStreams()
    
        if cls._show_progress:
            cls._progress_bar = Bar("Progress:", max = Parameters.MAX_SIMULATED_TIME)
    
        if Parameters.WRITE_LOGGING_INFO:
            logging.basicConfig(format = '%(message)s', level = logging.DEBUG,\
                filename = Parameters.LOG_FILENAME, filemode = 'w')
    
        if Parameters.WRITE_CSV_INFO:
            Symbiont.openCSVFile(Parameters.CSV_FILENAME)
    
        cls._num_symbionts : int = 0
        cls._num_symbionts_per_clade : list[int] = [0] * Parameters.NUM_CLADES
    
        # some setup for writing population time series
        cls._current_day : int = 1
        cls._prev_num_symbionts : int = 0
        cls._prev_num_symbionts_per_clade : list[int] = []
    
        cls._population_file = open(Parameters.POPULATION_FILENAME, "w")
    
        # create the sponge environment with initially-empty cells
        cls._num_rows : int    = Parameters.NUM_ROWS
        cls._num_cols : int    = Parameters.NUM_COLS
        cls._sponge   : Sponge = Sponge(cls._num_rows, cls._num_cols)
    
        # set the class-level sponge reference for all symbionts
        Symbiont.sponge = cls._sponge
    
        # create the event list -- initially empty except for the first arrival
        cls._event_list : EventList = EventList()
    
        ###################################################################################
        ###################################################################################
        ## INITIAL SYMBIONT SETUP
        ## Changed to use the if/else structure below to allow for either
        ##     (a) typical arrivals, for finding the multiple agents-zero
        ##     (b) no outside arrivals, plopping in based on geography
        allow_typical_arrivals : bool = True
        #allow_typical_arrivals : bool = False
    
        if allow_typical_arrivals:
            # schedule the first arrival to the system
            time  = RNG.exponential(Parameters.AVG_TIME_BETWEEN_ARRIVALS, Stream.ARRIVALS)
            event = Event(time, EventType.ARRIVAL, symbiont = None)
            cls._event_list.insertEvent(event)
    
        num_initial_agents : int = Parameters.NUM_INITIAL_SYMBIONTS
        initial_placement  : Placement = eval(f"Placement.{Parameters.INITIAL_PLACEMENT.upper()}")
    
        cls._current_time : float = 0.0

        which_clade : int = 0
        prev_clade_proportion : float = 0.0
        for n in range(num_initial_agents):
            if n / num_initial_agents > Symbiont.clade_cumulative_proportions[which_clade]:
                prev_clade_proportion = Symbiont.clade_cumulative_proportions[which_clade]
                which_clade = min(which_clade + 1, Parameters.NUM_CLADES - 1)
    
            clade_proportion = Symbiont.clade_cumulative_proportions[which_clade]

            if initial_placement == Placement.RANDOMIZE:
                open_cell = Symbiont.findOpenCell()
            ####
            elif initial_placement == Placement.HORIZONTAL:
                # place this clade at random within the appropriate
                # horizontal slice of the host
                row_start = int(Parameters.NUM_ROWS * prev_clade_proportion)
                row_end   = int(Parameters.NUM_ROWS * clade_proportion) 
                col_start = 0
                col_end   = Parameters.NUM_COLS
                open_cell = Symbiont.findOpenCellWithin(row_start, row_end, col_start, col_end)
            ####
            else:
                # place this clade at random within the appropriate
                # vertical slice of the host
                row_start = 0
                row_end   = Parameters.NUM_ROWS
                col_start = int(Parameters.NUM_COLS * prev_clade_proportion)
                col_end   = int(Parameters.NUM_COLS * clade_proportion) 
                open_cell = Symbiont.findOpenCellWithin(row_start, row_end, col_start, col_end)
    
            symbiont = Symbiont(which_clade, open_cell, cls._current_time)
            open_cell.setSymbiont(symbiont, cls._current_time)
    
            next_event_time, next_event_type = symbiont.getNextEvent()
            new_event = Event(next_event_time, next_event_type, symbiont)
            cls._event_list.insertEvent(new_event)
            cls._num_symbionts += 1
            cls._num_symbionts_per_clade[which_clade] += 1
            #num_symbionts_per_clade[symbiont._clade_number] += 1

            logging.debug(str(symbiont))
    
        ###################################################################################
        ###################################################################################
    
        ###################################################################################
        ###################################################################################
        # prepare to enter the main simulation loop...
        event = cls._event_list.getNextEvent()
        cls._end_time = Parameters.MAX_SIMULATED_TIME
    
        # write out t=0 population (which may not be zero for some experiments)
        string = ""
        total_population = 0
        for c in range(Parameters.NUM_CLADES):
            string += '\t'
            string += str(cls._num_symbionts_per_clade[c])
            total_population += cls._num_symbionts_per_clade[c]
            cls._prev_num_symbionts_per_clade.append(cls._num_symbionts_per_clade[c])
        string = f"0\t{total_population}{string}\n"
        cls._population_file.write(string)
    
        cls._prev_num_symbionts = total_population
    
        #############################################################
        # enter the main simulation loop
        while event is not None and event.getTime() < cls._end_time:
            ###################################
            cls._current_time = event.getTime()
            event_type = event.getType()
            symbiont   = event.getSymbiont()
    
            cls.writePopulation(cls._current_time)
            ###################################
    
            ###################################
            if event_type == EventType.ARRIVAL:
                #
                logging.debug('ARRIVAL @ t=%f' % (cls._current_time))
                # handle a symbiont arrival to the sponge -- 
                # check for affinity and open cell...
                symbiont = Symbiont.generateArrival(cls._current_time, cls._num_symbionts)
                if symbiont is not None:
                    # sufficient affinity to infect, so set up next event for symbiont
                    next_time, next_type = symbiont.getNextEvent()
                    new_event = Event(next_time, next_type, symbiont)
                    cls._event_list.insertEvent(new_event)
                    cls._num_symbionts += 1
                    cls._num_symbionts_per_clade[symbiont.getCladeNumber()] += 1
                
                logging.debug(str(symbiont))
    
                # schedule the next arrival
                next_time = cls._current_time + \
                    RNG.exponential(Parameters.AVG_TIME_BETWEEN_ARRIVALS, Stream.ARRIVALS)
                new_event = Event(next_time, EventType.ARRIVAL, symbiont = None)
                cls._event_list.insertEvent(new_event)
                #
            ####################################
            elif event_type == EventType.END_G0:
                #
                logging.debug('END G0 @ t=%f' % (cls._current_time))
                # handle a symbiont's end of G0 event
                symbiont.endOfG0(cls._current_time)
                # set up the next event for this symbiont -- G1SG2M or exit or digestion...
                next_time, next_type = symbiont.getNextEvent()
                new_event = Event(next_time, next_type, symbiont)
                cls._event_list.insertEvent(new_event)
                #
                logging.debug(str(symbiont))
                #
            ########################################
            elif event_type == EventType.END_G1SG2M:
                #
                logging.debug('END G1SG2M @ t=%f' % (cls._current_time))
                # handle a symbiont's end of G1SG2M event, which may result in a
                # built-in eviction event (see symbiont.py endOfG1SG2M())
                status, child = symbiont.endOfG1SG2M(cls._current_time)
                #
                logging.debug(f'status @ end of G1SG2M={status.name}')
                logging.debug(str(symbiont))
                logging.debug(str(child))
                #
                if status == SymbiontState.CHILD_INFECTS_OUTSIDE:
                    logging.debug(f'\t{status.name}')
                    child.csvOutputOnExit(cls._current_time, status)
                    # set up next events for parent (symbiont) only
                    next_time, next_type = symbiont.getNextEvent()
                    new_event = Event(next_time, next_type, symbiont)
                    cls._event_list.insertEvent(new_event)
                    #
                elif status == SymbiontState.PARENT_EVICTED:
                    logging.debug(f'\t{status.name}')
                    symbiont.csvOutputOnExit(cls._current_time, status)
                    # set up the next event for the child only 
                    # (who now occupies the cell)
                    next_time, next_type = child.getNextEvent()
                    new_event = Event(next_time, next_type, child)
                    cls._event_list.insertEvent(new_event)
                    #
                    logging.debug(f'RT = {cls._current_time - symbiont.getArrivalTime()} ({symbiont.getCladeNumber()})')
                    #
                elif status == SymbiontState.PARENT_INFECTS_OUTSIDE:
                    logging.debug(f'\t{status.name}')
                    symbiont.csvOutputOnExit(cls._current_time, status)
                    # set up the next event for the child only (who now occupies the cell)
                    next_time, next_type = child.getNextEvent()
                    new_event = Event(next_time, next_type, child)
                    cls._event_list.insertEvent(new_event)
                    #
                    logging.debug(f'RT = {cls._current_time - symbiont.getArrivalTime()} ({symbiont.getCladeNumber()})')
                    #
                elif status == SymbiontState.CHILD_EVICTED:
                    logging.debug(f'\t{status.name}')
                    child.csvOutputOnExit(cls._current_time, status)
                    # set up the next event for the parent only (who still occupies the cell)
                    next_time, next_type = symbiont.getNextEvent()
                    new_event = Event(next_time, next_type, symbiont)
                    cls._event_list.insertEvent(new_event)
                    #
                    logging.debug(f'RT = {cls._current_time - child.getArrivalTime()} ({child.getCladeNumber()})')
                    #
                elif status == SymbiontState.BOTH_STAY:
                    logging.debug(f'\t{status.name}')
                    # set up the next events for both symbionts
                    next_time, next_type = symbiont.getNextEvent()
                    new_event = Event(next_time, next_type, symbiont)
                    cls._event_list.insertEvent(new_event)
                    #
                    next_time, next_type = child.getNextEvent()
                    new_event = Event(next_time, next_type, child)
                    cls._event_list.insertEvent(new_event)
                    #
                    cls._num_symbionts += 1
                    cls._num_symbionts_per_clade[child.getCladeNumber()] += 1
                    #
                elif status == SymbiontState.PARENT_NO_AFFINITY:
                    logging.debug(f'\t{status.name}')
                    symbiont.csvOutputOnExit(cls._current_time, status)
                    # set up the next event for the child only (who now occupies the cell)
                    next_time, next_type = child.getNextEvent()
                    new_event = Event(next_time, next_type, child)
                    cls._event_list.insertEvent(new_event)
                    #
                    logging.debug(f'RT = {cls._current_time - symbiont.getArrivalTime()} ({symbiont.getCladeNumber()})')
                    #
                elif status == SymbiontState.CHILD_NO_AFFINITY:
                    logging.debug(f'\t{status.name}')
                    child.csvOutputOnExit(cls._current_time, status)
                    # set up the next event for the parent only (who still occupies the cell)
                    next_time, next_type = symbiont.getNextEvent()
                    new_event = Event(next_time, next_type, symbiont)
                    cls._event_list.insertEvent(new_event)
                    #
                    logging.debug(f'RT = {cls._current_time - child.getArrivalTime()} ({child.getCladeNumber()})')
                    #
                #
            #######################################
            elif event_type == EventType.DIGESTION:
                #
                logging.debug('DIGESTION @ t=%f' % (cls._current_time))
                # handle a symbiont-being-digested event
                symbiont.digestion(cls._current_time)
                prev_event_type = symbiont.getPrevEventType()
                if prev_event_type in (EventType.ARRIVAL, EventType.END_G1SG2M):
                    exit_status = SymbiontState.DIGESTION_IN_G0
                else:
                    exit_status = SymbiontState.DIGESTION_IN_G1SG2M
                symbiont.csvOutputOnExit(cls._current_time, exit_status)
                cls._num_symbionts -= 1
                cls._num_symbionts_per_clade[symbiont.getCladeNumber()] -= 1
                #
                # no further event updating for this symbiont -- the symbiont is gone!
                #
                logging.debug(str(symbiont))
                logging.debug(f'RT = {cls._current_time - symbiont.getArrivalTime()} ({symbiont.getCladeNumber()})')
                #
            #####################################
            elif event_type == EventType.ESCAPE:
                #
                logging.debug('ESCAPE @ t=%f' % (cls._current_time))
                # handle a symbiont-escaping-digestion event
                symbiont.escape(cls._current_time)
                prev_event_type = symbiont.getPrevEventType()
                if prev_event_type in (EventType.ARRIVAL, EventType.END_G1SG2M):
                    exit_status = SymbiontState.ESCAPE_IN_G0
                else:
                    exit_status = SymbiontState.ESCAPE_IN_G1SG2M
                symbiont.csvOutputOnExit(cls._current_time, exit_status)
                cls._num_symbionts -= 1
                cls._num_symbionts_per_clade[symbiont.getCladeNumber()] -= 1
                #
                # no further event updating for this symbiont -- the symbiont is gone!
                #
                logging.debug(str(symbiont))
                logging.debug(f'RT = {cls._current_time - symbiont.getArrivalTime()} ({symbiont.getCladeNumber()})')
                #
            ########################################
            elif event_type == EventType.DENOUEMENT:
                #
                logging.debug('DENOUEMENT @ t=%f' % (cls._current_time))
                # handle a symbiont-leaving-of-own-accord event
                symbiont.denouement(cls._current_time)
                prev_event_type = symbiont.getPrevEventType()
                if prev_event_type in (EventType.ARRIVAL, EventType.END_G1SG2M):
                    exit_status = SymbiontState.DENOUEMENT_IN_G0
                else:
                    exit_status = SymbiontState.DENOUEMENT_IN_G1SG2M
                symbiont.csvOutputOnExit(cls._current_time, exit_status)
                cls._num_symbionts -= 1
                cls._num_symbionts_per_clade[symbiont.getCladeNumber()] -= 1
                #
                # no further event updating for this symbiont -- the symbiont is gone!
                #
                logging.debug(str(symbiont))
                logging.debug(f'RT = {cls._current_time - symbiont.getArrivalTime()} ({symbiont.getCladeNumber()})')
                #
            # 
    
            logging.debug('>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>')
            event = cls._event_list.getNextEvent()
    
        # end of main simulation loop
        #######################################################
    
        # write out csv output for all symbionts still in residence at end
        Symbiont.csvOutputAtEnd(cls._current_time)
    
        cls.writePopulation(Parameters.MAX_SIMULATED_TIME)
        cls._population_file.close()
    
        if cls._show_progress: cls._progress_bar.finish()
    ## end of run()

##########################
if __name__ == "__main__":
    # kick off the main simulation loop
    Simulation.run()


