#!/usr/bin/env python

# Built-in modules
import time, datetime, threading, logging, sys, os.path
# Third-party modules
import lightblue, json
# Project modules
import daemon



# Logger setup stuff
logger = logging.getLogger('mbluepoint')
hdlr = logging.FileHandler('mbluepoint.log')
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
hdlr.setFormatter(formatter)
logger.addHandler(hdlr)
logger.setLevel(logging.INFO)



class SpamPointError(Exception):
	'''
	Base BlueBox SpamPoint exception
	'''
	pass



class MyOBEXClient(lightblue.obex.OBEXClient):
	'''Custom OBEX client class more hight-level that lightblue.obex.OBEXClient'''
	
	def __init__(self, addr, chn, name, devclass):
		print 'CLIENT', name
		lightblue.obex.OBEXClient.__init__(self, addr, chn)
		self.addr = addr
		self.chn = chn
		self.name = name
		self.devclass = devclass
	
	def send_file(self, camp):
		'''Hight-level method for send an file to the device'''
		print 'sending'
		mediafile = mbluepoint.camps[camp]['MEDIAFILE']
		filesize = os.path.getsize(mediafile)
		
		conn_resp = None
		put_resp = None
		
		# Open the file, connect and put this
		try:
			f = file(mediafile, 'rb')
			conn_resp = self.connect()
			put_resp = self.put({'name': mediafile.split('/')[-1],
								 'length': filesize}, f)
		# Ignore errors
		except lightblue.obex.OBEXError:
			'EXCEPT'
		# Close the file and try disconnect
		finally:
			f.close()
			try:
				self.disconnect()
			except:
				pass
			
		
		
		# if get FORBIDDEN response: update total_refused stat
		if put_resp:
			if put_resp.code == lightblue.obex.FORBIDDEN:
				mbluepoint.camps[camp]['LOG'].append([self.name, self.addr, 'refused', datetime.datetime.today().strftime('%d.%m.%Y-%H:%M:%S')])
				mbluepoint.camps[camp]['STATS']['TOTAL_REFUSED'] += 1
			
			# if get OK response: update total_accepted stats
			elif put_resp.code == lightblue.obex.OK:
				mbluepoint.camps[camp]['LOG'].append([self.name, self.addr, 'acepted', datetime.datetime.today().strftime('%d.%m.%Y-%H:%M:%S')])
				mbluepoint.camps[camp]['STATS']['TOTAL_ACCEPTED'] += 1
				# Then save the client address (MAC) in memcache
				logger.info('Caching %s in memcache (%s).' % (self.addr, camp))
				now = datetime.datetime.today()
				mbluepoint.camps[camp]['MEMCACHE'][self.addr] = now.strftime('%d.%m.%Y-%H:%M:%S')
		# If NONE response: update the total_failed stat
		else:
			mbluepoint.camps[camp]['LOG'].append([self.name, self.addr, 'failed', datetime.datetime.today().strftime('%d.%m.%Y-%H:%M:%S')])
			mbluepoint.camps[camp]['STATS']['TOTAL_FAILED'] += 1
			
		# Finally, update the total count stat
		mbluepoint.camps[camp]['STATS']['TOTAL'] += 1



class mBluePoint(daemon.Daemon):

	def __init__(self, pidfile):
		daemon.Daemon.__init__(self, pidfile)
		self.camps = None
	
	def _restore_new(self):
		logger.info('Restoring new index file "index.yaml.new"')
		if os.path.isfile('index.yaml.new'):
			os.remove('index.yaml')
			os.rename('index.yaml.new', 'index.yaml')
	
	def load_camps(self):
		'''
		Load the campaigns file
		'''
		f = open('index.yaml', 'r')
		self.camps = json.decode(f.read())
		f.close()

	def save_camps(self):
		'''
		Save the campaign file
		'''
		f = open('index.yaml', 'w')
		f.write(json.encode(self.camps))
		f.close()
	
	def scan(self):
		'''
		Scan nearby devices searching devices
		offering "OBEX Object Push" service
		'''
		nearby = lightblue.finddevices(True, 10)
		obex_devices = []
		for dev_data in nearby:
			obex_data = lightblue.findservices(addr=dev_data[0], name=u'OBEX Object Push')
			if obex_data:
				addr, chn, name, devclass = obex_data[0][0], obex_data[0][1], dev_data[1], dev_data[2]
				obex_devices.append(MyOBEXClient(addr, chn, name, devclass))

		logger.info('Obex Scan: %s' % [d[1] for d in nearby])
		return obex_devices

	def clean_cache(self):
		'''
		Clean the cache searching devices addrs with expireds dates
		'''
		for camp in self.camps:
			timedelta = datetime.timedelta(seconds=self.camps[camp]['MEMCACHELIFE'])
			
			for_del = []
			for dev in self.camps[camp]['MEMCACHE']:
				# Build the objects
				now = datetime.datetime.today()
				date, time = self.camps[camp]['MEMCACHE'][dev].split('-')
				date, time = date.split('.'), time.split(':')
				
				cachedtime = datetime.datetime(int(date[2]), int(date[1]),
											   int(date[0]), int(time[0]), int(time[1]))
				
				# Datetime expired?
				if cachedtime + timedelta <= now:
					for_del.append(dev)
			for dev in for_del:
				logger.info('Uncaching %s..' % self.camps[camp]['MEMCACHE'][dev])			
				del self.camps[camp]['MEMCACHE'][dev]


	def start(self):
		'''
		Turn on the mBluePoint
		'''
		logger.info('-------- Starting BlueBox (mBluePoint) --------')		
		
		# Restore the .new if exist
		self._restore_new()
		
		# Read possibles config changes		
		self.load_camps()
		
		# Restore the NEW yaml file
		# TODO
		
		while 1:
			# Clean the memcache of olds clients
			self.clean_cache()
			# Scan searching devices
			clients = self.scan()
			# Loop over founds clients
			for client in clients:
				# Loop over camps
				for camp in self.camps:
					
					# Build the time objects for check the schedule
					start, stop = self.camps[camp]['SCHEDULE'][0], self.camps[camp]['SCHEDULE'][1]
					start, stop = start.split(':'), stop.split(':')
					if len(start) and len(stop) == 3:
						start = datetime.time(int(start[0]), int(start[1]), int(start[2]), 0)
						stop = datetime.time(int(stop[0]),int(stop[1]), int(stop[2]), 0)
						now = datetime.datetime.today()
						now = datetime.time(now.hour, now.minute, now.second)
					# Valid time format?
					else:
						raise SpamPointError, 'Schedule start or stop options corrupted'
					
					# Finally, Are the camp actived in time?
					if (now >= start) and (now <= stop):
						# If the device MAC not cached?
						addr = client.addr
						if not addr in self.camps[camp]['MEMCACHE']:
							
							# Exist the file?
							mediafile = self.camps[camp]['MEDIAFILE']
							if not os.path.isfile(mediafile):
								# Raise an exeption
								raise SpamPointError, '%s file not found' % mediafile
							
							# Start the send in thready
							t = threading.Thread(target=client.send_file, args=(camp,) )
							t.start()
	
			# Save the memcache changes
			self.save_camps()
			logger.info('Data backup saved.')
			
			# Pause the CPU a bit little
			time.sleep(15)	

	# Daemon stuff
	def run(self):
		while True:
			time.sleep(1)



# Dummy singleton pattern
mbluepoint = mBluePoint('/tmp/bluebox-mbluepoint.pid')



if __name__ == '__main__':
	if len(sys.argv) == 2:
		if 'start' == sys.argv[1]:
			mbluepoint.start()
		elif 'stop' == sys.argv[1]:
			mbluepoint.stop()
		elif 'restart' == sys.argv[1]:
			mbluepoint.restart()
		else:
			print "Unknown command"
			sys.exit(2)
		sys.exit(0)
	else:
		print '\nBluebox mBluePoint\nUsage: %s start|stop|restart\n' % sys.argv[0]
		sys.exit(2)



