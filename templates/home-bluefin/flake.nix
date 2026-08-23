{
  description = "Finite Bluefin Home Manager bootstrap";
  inputs.finite.url = "github:closure-labs/finite";
  inputs.nixpkgs.follows = "finite/nixpkgs";
  outputs = {finite, ...}: {
    apps.x86_64-linux = {
      home-profile = finite.apps.x86_64-linux.home-profile;
      home-bootstrap = finite.apps.x86_64-linux.home-bootstrap;
      default = finite.apps.x86_64-linux.home-bootstrap;
    };
  };
}
