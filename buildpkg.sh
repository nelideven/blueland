#!/bin/bash


#blueland - A reactive Bluetooth frontend daemon for Hyprland users.
#This library is free software; you can redistribute it and/or modify it under the terms of the GNU Lesser General Public License as published by the Free Software Foundation; either version 2.1 of the License, or (at your option) any later version.
#This library is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more details.
#You should have received a copy of the GNU Lesser General Public License along with this library; if not, see <https://www.gnu.org/licenses/>.


# Requesting for sudo
if [ "$EUID" -ne 0 ]; then
  echo "Requesting sudo access to build package..."
  sudo -v
fi

# Removing old buildpkg folder just in case
sudo rm -rf /tmp/blueland-pkg/

# Build structure
mkdir -p /tmp/blueland-pkg/usr/bin/
mkdir -p /tmp/blueland-pkg/usr/share/dbus-1/services
mkdir -p /tmp/blueland-pkg/etc/systemd/user

# Copy files
cp -r ./DEBIAN /tmp/blueland-pkg/
cp ./org.blueland.Agent.service /tmp/blueland-pkg/usr/share/dbus-1/services
cp ./blueland.service /tmp/blueland-pkg/etc/systemd/user
cp ./blueland.py /tmp/blueland-pkg/usr/bin/blueland

# Permissions
sudo chown -R root:root /tmp/blueland-pkg/
find /tmp/blueland-pkg/ -type d -exec sudo chmod 755 {} \;
find /tmp/blueland-pkg/ -type f -exec sudo chmod 644 {} \;
sudo chmod 755 /tmp/blueland-pkg/DEBIAN/postinst
sudo chmod 755 /tmp/blueland-pkg/usr/bin/blueland

# Build debian package
dpkg-deb --build /tmp/blueland-pkg/ "$HOME/blueland.deb"

# Additional install.sh file for tarball
sudo tee /tmp/blueland-pkg/install.sh > /dev/null << 'EOF'
#!/bin/bash

echo "Installing Blueland Agent..."

# Copy all extracted contents to root
for dir in usr etc; do
  sudo cp -r "$dir" /
done

# Reload systemd (user mode)
systemctl --user daemon-reexec
systemctl --user daemon-reload

# Enable and start the service
systemctl --user enable blueland.service
systemctl --user start blueland.service

echo "Blueland Agent installed and running"
EOF
sudo chmod 755 /tmp/blueland-pkg/install.sh
tar -czvf "$HOME/blueland.tar.gz" --exclude='DEBIAN' -C /tmp/blueland-pkg/ .
