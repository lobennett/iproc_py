import configparser

class Config(object):
    def __init__(self):
        self._config = None
        self._sections = []

    def parse(self, f):
        self._config = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation())
        self._config.read(f)
        for section in self._config.sections():
            self.__dict__[section] = ConfigSection(self._config,section)
            self._sections.append(section)

    def __contains__(self, name):
        try:
            for section in self._sections:
                self.__dict__[section].get(section, name)
        except configparser.NoOptionError:
            return False
        return True

    def items(self):
        items={}
        for section in self._config.sections():
            items[section] = self._config.items(section)
        return items

    # for manually accessing config options with arbitrary sections
    # though you should usually use namespace notation instead
    def get(self, section, name, default=None):
        try:
            return self._config.get(section, name)
        except configparser.NoOptionError:
            return default
        except configparser.NoSectionError:
            return default

    # for adding config options with arbitrary sections and values not present 
    #in config file
    def set(self, section, name, value):
        self._config.set(section, name, value)

class ConfigSection(object):
# intended to be used in a Config class, to enable multilevel namespace access of variables.
    def __init__(self, config, section_name):
        # must define section first, as it is used on overloaded internal methods
        self.section = section_name
        self._config = config

    def __contains__(self, name):
        try:
            self._config.get(self.section, name)
        except configparser.NoOptionError:
            return False
        return True

    def items(self):
        return self._config.items(self.section)

    def get(self, name):
        return self._config.get(self.section, name)

    def set(self, name, value):
        self._config.set(self.section, name, value)
    
    # These allow us to access the configparser items dynamically,
    #but as if they were predefined class members in the namespace
    def __getattr__(self, name):
        try:
            return self.get(name)
        except configparser.NoOptionError:
            raise ConfigError("No config option '{0}'".format(name))
    
    def __setattr__(self, name, value):
        #make sure we can add mandatory members normally
        if name == '_config':
            self.__dict__['_config'] = value
        elif name == 'section':
            self.__dict__['section'] = value
        else:
            # pass on to _config for handling
            self.set(name, value)

class ConfigError(Exception):
    pass

