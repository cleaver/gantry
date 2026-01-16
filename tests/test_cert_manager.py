"""Tests for certificate manager with mkcert subprocess mocking."""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gantry.cert_manager import CERTS_DIR, CertManager, MKCERT_PATH


@pytest.fixture
def mock_mkcert_path(tmp_path, monkeypatch):
    """Create a mock mkcert path that exists."""
    mock_path = tmp_path / "mkcert"
    mock_path.touch()
    return mock_path


@pytest.fixture
def cert_manager(mock_mkcert_path, monkeypatch):
    """Create a CertManager instance with mocked mkcert path."""
    with patch("gantry.cert_manager.MKCERT_PATH", mock_mkcert_path):
        manager = CertManager()
        manager._mkcert_path = mock_mkcert_path
        return manager


class TestCertGeneration:
    """Test certificate generation with subprocess mocking."""
    
    def test_generate_cert_single_domain(self, cert_manager, tmp_path, monkeypatch):
        """Test certificate generation with single domain."""
        # Mock CERTS_DIR to use tmp_path
        mock_certs_dir = tmp_path / "certs"
        monkeypatch.setattr("gantry.cert_manager.CERTS_DIR", mock_certs_dir)
        
        with patch("subprocess.run") as mock_run:
            # Mock successful subprocess call
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "Created a new certificate"
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            
            result = cert_manager.generate_cert(["example.test"])
            
            assert result is True
            
            # Verify subprocess was called with correct arguments
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert str(cert_manager._mkcert_path) in call_args
            assert "-cert-file" in call_args
            assert "-key-file" in call_args
            assert "example.test" in call_args
            
            # Verify file paths in command
            # For "example.test", filename should be "example.test.pem" (not wildcard)
            cert_file_arg = call_args[call_args.index("-cert-file") + 1]
            assert "example.test.pem" in str(cert_file_arg)
            key_file_arg = call_args[call_args.index("-key-file") + 1]
            assert "example.test-key.pem" in str(key_file_arg)
    
    def test_generate_cert_multiple_domains(self, cert_manager, tmp_path, monkeypatch):
        """Test certificate generation with multiple domains (wildcard, localhost)."""
        mock_certs_dir = tmp_path / "certs"
        monkeypatch.setattr("gantry.cert_manager.CERTS_DIR", mock_certs_dir)
        
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "Created a new certificate"
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            
            domains = ["*.test", "localhost"]
            result = cert_manager.generate_cert(domains)
            
            assert result is True
            
            # Verify all domains are in command
            call_args = mock_run.call_args[0][0]
            assert "*.test" in call_args
            assert "localhost" in call_args
            
            # Verify wildcard is converted to wildcard. prefix in filename
            cert_file_arg = call_args[call_args.index("-cert-file") + 1]
            assert "wildcard.test" in str(cert_file_arg)
    
    def test_generate_cert_file_paths(self, cert_manager, tmp_path, monkeypatch):
        """Test certificate file paths and naming."""
        mock_certs_dir = tmp_path / "certs"
        monkeypatch.setattr("gantry.cert_manager.CERTS_DIR", mock_certs_dir)
        
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            
            cert_manager.generate_cert(["example.test"])
            
            # Verify directory creation
            assert mock_certs_dir.exists() or mock_certs_dir.parent.exists()
            
            # Verify command includes correct file paths
            call_args = mock_run.call_args[0][0]
            cert_file_idx = call_args.index("-cert-file")
            key_file_idx = call_args.index("-key-file")
            
            cert_file = call_args[cert_file_idx + 1]
            key_file = call_args[key_file_idx + 1]
            
            # Both files should be in the certs directory
            assert str(mock_certs_dir) in str(cert_file)
            assert str(mock_certs_dir) in str(key_file)
            # Verify file extensions
            assert str(cert_file).endswith(".pem")
            assert str(key_file).endswith("-key.pem")
    
    def test_generate_cert_mkcert_not_found(self, tmp_path, monkeypatch):
        """Test certificate generation when mkcert is not found."""
        # Create manager with non-existent mkcert path
        non_existent_path = tmp_path / "nonexistent" / "mkcert"
        with patch("gantry.cert_manager.MKCERT_PATH", non_existent_path):
            manager = CertManager()
            manager._mkcert_path = non_existent_path
            
            result = manager.generate_cert(["example.test"])
            
            assert result is False
    
    def test_generate_cert_no_domains(self, cert_manager):
        """Test certificate generation with no domains."""
        result = cert_manager.generate_cert([])
        assert result is False
    
    def test_generate_cert_subprocess_error(self, cert_manager, tmp_path, monkeypatch):
        """Test certificate generation subprocess error handling."""
        mock_certs_dir = tmp_path / "certs"
        monkeypatch.setattr("gantry.cert_manager.CERTS_DIR", mock_certs_dir)
        
        with patch("subprocess.run") as mock_run:
            # Mock subprocess error
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "mkcert", stderr="Error: CA not installed"
            )
            
            result = cert_manager.generate_cert(["example.test"])
            
            assert result is False
    
    def test_generate_cert_command_arguments(self, cert_manager, tmp_path, monkeypatch):
        """Test that subprocess command arguments match expected mkcert syntax."""
        mock_certs_dir = tmp_path / "certs"
        monkeypatch.setattr("gantry.cert_manager.CERTS_DIR", mock_certs_dir)
        
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            
            cert_manager.generate_cert(["test.example"])
            
            # Verify subprocess.run was called with check=True
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["check"] is True
            assert call_kwargs["capture_output"] is True
            assert call_kwargs["text"] is True


class TestCASetup:
    """Test CA setup with subprocess mocking."""
    
    def test_setup_ca_success(self, cert_manager):
        """Test successful CA setup."""
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "The local CA is now installed"
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            
            result = cert_manager.setup_ca()
            
            assert result is True
            
            # Verify subprocess was called with -install flag
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert str(cert_manager._mkcert_path) in call_args
            assert "-install" in call_args
    
    def test_setup_ca_failure(self, cert_manager):
        """Test CA setup failure."""
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = ""
            mock_result.stderr = "Error: Permission denied"
            mock_run.return_value = mock_result
            
            result = cert_manager.setup_ca()
            
            assert result is False
    
    def test_setup_ca_mkcert_not_found(self, tmp_path):
        """Test CA setup when mkcert is not found."""
        non_existent_path = tmp_path / "nonexistent" / "mkcert"
        with patch("gantry.cert_manager.MKCERT_PATH", non_existent_path):
            manager = CertManager()
            manager._mkcert_path = non_existent_path
            
            result = manager.setup_ca()
            
            assert result is False
    
    def test_setup_ca_subprocess_exception(self, cert_manager):
        """Test CA setup with subprocess exception."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("mkcert not found")
            
            result = cert_manager.setup_ca()
            
            assert result is False
    
    def test_setup_ca_command_arguments(self, cert_manager):
        """Test that setup_ca uses correct subprocess arguments."""
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            
            cert_manager.setup_ca()
            
            # Verify subprocess.run was called with check=False
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["check"] is False
            assert call_kwargs["capture_output"] is True
            assert call_kwargs["text"] is True


class TestCAStatus:
    """Test CA status checking with subprocess mocking."""
    
    def test_get_ca_status_installed(self, cert_manager, tmp_path):
        """Test getting CA status when CA is installed."""
        # Mock CAROOT output
        ca_root = tmp_path / "ca-root"
        ca_root.mkdir()
        ca_file = ca_root / "rootCA.pem"
        ca_file.touch()
        
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = str(ca_root) + "\n"
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            
            with patch.object(Path, "exists", return_value=True):
                status = cert_manager.get_ca_status()
                
                assert status["installed"] is True
                assert status["path"] == str(ca_file)
    
    def test_get_ca_status_not_installed(self, cert_manager, tmp_path):
        """Test getting CA status when CA is not installed."""
        ca_root = tmp_path / "ca-root"
        
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = str(ca_root) + "\n"
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            
            with patch.object(Path, "exists", return_value=False):
                status = cert_manager.get_ca_status()
                
                assert status["installed"] is False
                assert status["path"] is None
    
    def test_get_ca_status_mkcert_not_found(self, tmp_path):
        """Test getting CA status when mkcert is not found."""
        non_existent_path = tmp_path / "nonexistent" / "mkcert"
        with patch("gantry.cert_manager.MKCERT_PATH", non_existent_path):
            manager = CertManager()
            manager._mkcert_path = non_existent_path
            
            status = manager.get_ca_status()
            
            assert status["installed"] is False
            assert status["path"] is None
    
    def test_get_ca_status_subprocess_error(self, cert_manager):
        """Test getting CA status when subprocess fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "mkcert")
            
            status = cert_manager.get_ca_status()
            
            assert status["installed"] is False
            assert status["path"] is None
    
    def test_get_ca_status_file_not_found_error(self, cert_manager):
        """Test getting CA status when FileNotFoundError occurs."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("mkcert not found")
            
            status = cert_manager.get_ca_status()
            
            assert status["installed"] is False
            assert status["path"] is None
    
    def test_get_ca_status_command_arguments(self, cert_manager, tmp_path):
        """Test that get_ca_status uses correct subprocess arguments."""
        ca_root = tmp_path / "ca-root"
        
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = str(ca_root) + "\n"
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            
            # Create a mock path that exists
            mock_mkcert_path = MagicMock(spec=Path)
            mock_mkcert_path.exists.return_value = True
            mock_mkcert_path.__str__ = lambda self: "/fake/mkcert"
            
            # Patch the mkcert_path to ensure exists() returns True
            with patch.object(cert_manager, "_mkcert_path", mock_mkcert_path):
                # Patch Path.exists for the ca_path check to return False
                with patch("pathlib.Path.exists", return_value=False):
                    cert_manager.get_ca_status()
                    
                    # Verify subprocess was called
                    assert mock_run.called
                    
                    # Verify subprocess was called with -CAROOT flag
                    call_args = mock_run.call_args
                    assert call_args is not None
                    positional_args = call_args[0] if isinstance(call_args, tuple) else call_args.args
                    assert "-CAROOT" in positional_args[0]
                    
                    # Verify subprocess.run was called with check=True
                    call_kwargs = call_args[1] if isinstance(call_args, tuple) else call_args.kwargs
                    assert call_kwargs["check"] is True
                    assert call_kwargs["capture_output"] is True
                    assert call_kwargs["text"] is True


class TestDirectoryCreation:
    """Test directory creation for certificates."""
    
    def test_generate_cert_creates_certs_dir(self, cert_manager, tmp_path, monkeypatch):
        """Test that generate_cert creates CERTS_DIR if it doesn't exist."""
        mock_certs_dir = tmp_path / "certs"
        monkeypatch.setattr("gantry.cert_manager.CERTS_DIR", mock_certs_dir)
        
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            
            with patch.object(Path, "mkdir") as mock_mkdir:
                cert_manager.generate_cert(["example.test"])
                
                # Verify mkdir was called with parents=True, exist_ok=True
                mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
