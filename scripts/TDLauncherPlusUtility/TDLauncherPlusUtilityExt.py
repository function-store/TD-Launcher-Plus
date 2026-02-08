import os
import platform
import json
import time

CustomParHelper: CustomParHelper = next(d for d in me.docked if 'ExtUtils' in d.tags).mod('CustomParHelper').CustomParHelper # import
###

class TDLauncherPlusUtilityExt:
	def __init__(self, ownerComp):
		CustomParHelper.Init(self, ownerComp, enable_properties=True, enable_callbacks=True)
		self.ownerComp = ownerComp
		self.icon_source = self.ownerComp.op('null_icon')

		run(lambda: self.postInit(), endFrame=True)

	def postInit(self):
		self.SaveRecents()

	def getConfigPath(self):
		system = platform.system()
		if system == 'Windows':
			base = os.environ.get('APPDATA', os.path.expanduser('~'))
			config_dir = os.path.join(base, 'TD Launcher Plus')
		elif system == 'Darwin':  # macOS
			config_dir = os.path.expanduser('~/.config/td-launcher')
		else:
			xdg_config = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
			config_dir = os.path.join(xdg_config, 'td-launcher')
			
		return os.path.join(config_dir, 'config.json')

	def loadConfig(self):
		path = self.getConfigPath()
		if not os.path.exists(path):
			return {}
		try:
			with open(path, 'r', encoding='utf-8') as f:
				return json.load(f)
		except Exception as e:
			debug(f"TDLauncherUtility: Error loading config: {e}")
			return {}

	def SaveRecents(self):
		"""
		Overwrite the 'recent_files' list in the config.
		recents: List of dicts [{'path': str, 'last_opened': float}]
		"""
		### Handled by discovery of recent list in OS registry
		return
		"""recents = app.recentFiles
		debug(f'Recents: {recents}')
		path = self.getConfigPath()
		config = self.loadConfig()
		
		# Update property - use 'td_recents' to avoid overwriting launcher's local history
		config['td_recents'] = recents
		config['td_recents_timestamp'] = time.time()
		
		# Ensure dir exists
		os.makedirs(os.path.dirname(path), exist_ok=True)
		
		try:
			with open(path, 'w', encoding='utf-8') as f:
				json.dump(config, f, indent=2)
		except Exception as e:
			debug(f"TDLauncherUtility: Error saving config: {e}")"""

	def onParSaveicon(self):
		self.SaveIcon(is_temp = False)

	def SaveIcon(self, is_temp = True):
		"""
		Save icon_{project_base_name}.png to support unique icons for multiple projects in the same folder.
		"""
		if not self.evalSavetempicon:
			return
		
		# Determine base name (strip .toe and version number)
		name = project.name
		if name.lower().endswith('.toe'):
			name = name[:-4]
			
		# Strip version number (e.g. Project.1 -> Project)
		if '.' in name:
			parts = name.rsplit('.', 1)
			if parts[1].isdigit():
				name = parts[0]
				
		# Prepend 'temp_' if this is an auto-generated temporary icon
		prefix = "temp_" if is_temp else ""
		filename = f'icon_{prefix}{name}.png'
		
		self.icon_source.save(filename, quality = 0.5, metadata=[("source","TDLauncherPlusUtility"), ("project_name", project.name)])


	


